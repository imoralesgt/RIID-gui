import numpy as np
from scipy.signal import savgol_filter

# Parameters 
T_BACKGROUND = 1800
data_path    = "data/"

from io_utils import (
    read_spec, read_measurement_time, read_spectrum_file,
    read_calibration, resample_to_energy_grid,
    DEFAULT_CAL_A, DEFAULT_CAL_B, CANONICAL_ENERGIES,
)


# ::: Background substraction :::
#  Background subtraction fallback: file measDetA013.spe
# Read and immediately resample to canonical energy grid
try:
    _raw_bg = read_spec(data_path + "measDetA013.spe")
    background_raw = resample_to_energy_grid(_raw_bg, DEFAULT_CAL_A, DEFAULT_CAL_B)
except FileNotFoundError:
    import sys
    print(f"WARNING: Default background file '{data_path}measDetA013.spe' not found.", file=sys.stderr)
    print("Background subtraction will fall back to zeros unless a custom background is passed.", file=sys.stderr)
    background_raw = np.zeros(2048)


def subtract_background(counts, measurement_time, bg_counts=None, bg_time=None):
    """Subtracts the background from a spectrum.

    Scales the background counts to the measurement time and subtracts them
    from the input spectrum, clipping negative values to zero.

    Args:
        counts (np.ndarray): Raw spectrum counts.
        measurement_time (float): Measurement time of the input spectrum in seconds.
        bg_counts (np.ndarray, optional): Background spectrum counts. Defaults to
            the module-level `background_raw`.
        bg_time (float, optional): Measurement time of the background spectrum in
            seconds. Defaults to the module-level `T_BACKGROUND`.

    Returns:
        np.ndarray: Background-subtracted spectrum with negative values clipped to zero.
    """
    if bg_counts is None:
        bg_counts = background_raw
        
    if bg_time is None:
        bg_time = T_BACKGROUND
        
    n = min(len(counts), len(bg_counts))

    return np.clip(counts[:n] - bg_counts[:n] * (measurement_time / bg_time), 0, None)

# ::: Preprocessing functions :::
def preprocess_no_log(counts, crop_bins=20, decimation=8):
    """Preprocesses a spectrum using Savitzky-Golay smoothing and decimation.

    Crops the low-energy bins, applies Savitzky-Golay smoothing, decimates,
    and normalizes the spectrum.

    Args:
        counts (np.ndarray): Raw spectrum counts.
        crop_bins (int, optional): Number of low-energy bins to crop. Defaults to 20.
        decimation (int, optional): Decimation factor. Defaults to 8.

    Returns:
        np.ndarray: Preprocessed and normalized spectrum.
    """
    counts = counts[crop_bins:]
    smooth = savgol_filter(counts, window_length=11, polyorder=3)
    smooth = np.clip(smooth, 0, None)
    dec = smooth[::decimation]
    return dec / (dec.sum() + 1e-8)

def preprocess_log(counts, crop_bins=20, decimation=8):
    """Preprocesses a spectrum applying log scaling, smoothing and decimation.

    Crops the low-energy bins, applies log10 scaling, Savitzky-Golay smoothing,
    decimates, and normalizes the spectrum.

    Args:
        counts (np.ndarray): Raw spectrum counts.
        crop_bins (int, optional): Number of low-energy bins to crop. Defaults to 20.
        decimation (int, optional): Decimation factor. Defaults to 8.

    Returns:
        np.ndarray: Log-scaled, preprocessed and normalized spectrum.
    """

    counts = counts[crop_bins:]
    log = np.log10(counts + 1)
    smooth = savgol_filter(log, window_length=11, polyorder=3)
    smooth = np.clip(smooth, 0, None)
    dec = smooth[::decimation]
    return dec / (dec.sum() + 1e-8)

def preprocess_baseline(counts):
    """Preprocesses a spectrum with fixed-length normalization.

    Ensures a fixed length of 2047 bins by truncating or zero-padding,
    then normalizes the spectrum.

    Args:
        counts (np.ndarray): Raw spectrum counts.

    Returns:
        np.ndarray: Fixed-length normalized spectrum of shape (2047,).
    """
    # Ensure fixed length of 2047 (some files have 2048, others 2047)
    counts = counts[:2047]
    if len(counts) < 2047:
        counts = np.pad(counts, (0, 2047 - len(counts)))
    return counts / (counts.sum() + 1e-8)

# :::  Region of Interest (ROI)  
# On the canonical energy grid each bin = 1 keV, so channel ≈ energy in keV.
def energy_to_channel(E_kev, a=0.0, b=1.0):
    """Map an energy (keV) to its bin index on the canonical 1-keV grid."""

    return int(round(E_kev))

# ROI definition
ROI = {
    "137Cs": [
        (energy_to_channel(184),  30),   
        (energy_to_channel(477),  40),   
        (energy_to_channel(662),  50),   
    ],
    "60Co": [
        (energy_to_channel(1063), 40),   
        (energy_to_channel(1173), 50),   
        (energy_to_channel(1332), 50),   
    ],
    "152Eu": [
        (energy_to_channel(122),  25),   
        (energy_to_channel(245),  30),   
        (energy_to_channel(344),  35),   
        (energy_to_channel(779),  40),   
        (energy_to_channel(964),  40),   
        (energy_to_channel(1086), 40),   
        (energy_to_channel(1112), 40),   
        (energy_to_channel(1408), 45),   
    ],
    # Background signatures
    "bkg": [
        (energy_to_channel(609),  35),   
        (energy_to_channel(1460), 45),   
    ],
}

# ROI preprocessing 
def preprocess_roi(counts):
    """Extracts and normalizes Region of Interest (ROI) features from a spectrum.

    Applies Savitzky-Golay smoothing and extracts statistical features from
    predefined ROI windows for each source, including max, sum, argmax, std,
    mean, percentiles, peak-to-mean ratio, area under the curve, and center bin.

    Args:
        counts (np.ndarray): Raw spectrum counts.

    Returns:
        np.ndarray: Normalized feature vector extracted from the ROI windows,
            scaled by the maximum absolute value.
    """

    smooth = savgol_filter(counts, window_length=11, polyorder=3)
    smooth = np.clip(smooth, 0, None)

    features = []
    for source, regions in ROI.items():
        for channel, width in regions:
            c_start = max(0, channel - width)
            c_end = min(len(smooth), channel + width)
            window = smooth[c_start:c_end]
            features.append(window.max())
            features.append(window.sum())
            features.append(float(window.argmax()))
            features.append(window.std())
            features.append(window.mean())
            features.append(np.percentile(window, 75))
            features.append(np.percentile(window, 25))
            features.append(window.max() / (window.mean() + 1e-8))
            features.append(np.trapezoid(window))
            # features.append(np.trapz(window))
            features.append(window[len(window)//2])

    features = np.array(features)

    return features / (np.abs(features).max() + 1e-8)
