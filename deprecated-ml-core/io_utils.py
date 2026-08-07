import numpy as np
import json
import re
from scipy.interpolate import interp1d

#  Default calibration (data/ folder - detector SiPM-210328BE3C07B) 
DEFAULT_CAL_A = -16.23    # intercept [keV]
DEFAULT_CAL_B = 1.0292   # slope     [keV/channel]

# MCA / detector calibration lookup table 
# Keyed by MCA serial number as it appears in $SPEC_REM.
# data2, data3, data4 were all acquired with MCA SN:210328BE425FB
# (confirmed from .spe headers and .json metadata: a=-14.7491, b=1.01628).
# data1 has no $SPEC_REM block: falls through to DEFAULT_CAL_*.
MCA_CAL_TABLE = {
    "210328BE425FB": (-14.7491, 1.01628),
}

# Canonical energy grid shared across all datasets 
# 0–2047 keV at 1 keV/bin
# 2048 bins, independent of detector calibration.
CANONICAL_ENERGIES = np.arange(2048, dtype=float)   # keV

def read_spec(filename):
    """Reads counts array from a .spe file.

    Parses the $DATA: block from an SPE file, handling NSIL format with
    comma-separated headers, and returns the spectrum counts as a float array.

    Args:
        filename (str): Path to the .spe file.

    Returns:
        np.ndarray: Spectrum counts as a float array. Returns zeros array of
            length 2048 if the $DATA: block is not found.
    """

    with open(filename, "r") as f:
        content = f.read()
    idx   = content.find("$DATA:")
    if idx == -1:
        return np.zeros(2048)
    block = content[idx + len("$DATA:"):].strip()
    sig   = block.find("$")
    if sig != -1:
        block = block[:sig]
    # Strip comma separators (format: "0, 2047" in header line)
    numbers = [n.rstrip(',') for n in block.split()]

    return np.array([int(n) for n in numbers[2:]], dtype=float)


def read_measurement_time(filename):
    """Reads the live time from a .spe file.

    Searches for the $MEAS_TIM: or $REAL_TIME: tag and extracts
    the first value as the measurement time in seconds.

    Args:
        filename (str): Path to the .spe file.

    Returns:
        float: Measurement time in seconds, or None if no time tag is found.
    """
    with open(filename, "r") as f:
        content = f.read()
    for tag in ["$MEAS_TIM:", "$REAL_TIME:"]:
        idx = content.find(tag)
        if idx != -1:
            line = content[idx + len(tag):].strip().split("\n")[0]
            return float(line.split()[0])

    return None


def _mca_sn_from_spe(spe_content):
    """Extracts the MCA serial number from the $SPEC_REM block of a .spe file.

    Args:
        spe_content (str): Full content of the .spe file as a string.

    Returns:
        str: MCA serial number, or None if not found.
    """
    m = re.search(r"MCA:.*?SN:(\S+)", spe_content)
    return m.group(1) if m else None


def read_calibration(fpath):
    """Extracts energy calibration coefficients from a spectrum file.

    Tries the following sources in order:
        1. JSON quadratic calibration fields.
        2. JSON Analyzer fields ('Analyzer offset/gain').
        3. MCA serial number lookup from $SPEC_REM in the .spe header.
        4. Fallback to DEFAULT_CAL_A and DEFAULT_CAL_B.

    Args:
        fpath (str): Path to the .spe or .json spectrum file.

    Returns:
        tuple[float, float, float]: Calibration coefficients (a, b, c) where
            E(keV) = a + b * ch + c * ch². Returns c=0.0 when no quadratic
            term is available.
    """

    def _parse_json_cal(path):
        """Try quadratic first, then linear Analyzer fields."""
        try:
            with open(path) as f:
                d = json.load(f)
            meta = d.get("metadata", {})

            # Prefer quadratic Energy calibration when available
            if "Energy calibration linear (keV/ch)" in meta:
                a = float(meta["Energy calibration offset (keV)"])
                b = float(meta["Energy calibration linear (keV/ch)"])
                c = float(meta.get("Energy calibration quadratic (keV/ch2)", 0.0))
                return a, b, c

            # Fall back to linear Analyzer fields
            if "Analyzer gain (keV/ch)" in meta:
                b = float(meta["Analyzer gain (keV/ch)"])
                a = float(meta["Analyzer offset (keV)"])
                return a, b, 0.0

        except (KeyError, ValueError, json.JSONDecodeError, OSError):
            pass
        return None

    # Direct JSON or JSON sidecar
    if fpath.endswith(".json"):
        result = _parse_json_cal(fpath)
        if result:
            return result
        
    elif fpath.endswith(".spe"):
        json_sidecar = fpath.rsplit(".", 1)[0] + ".json"
        result = _parse_json_cal(json_sidecar)
        if result:
            return result

    # MCA lookup from .spe header
    spe_path = fpath if fpath.endswith(".spe") else fpath.rsplit(".", 1)[0] + ".spe"
    try:
        with open(spe_path) as f:
            content = f.read()
        sn = _mca_sn_from_spe(content)
        if sn and sn in MCA_CAL_TABLE:
            a, b = MCA_CAL_TABLE[sn]
            return a, b, 0.0
    except OSError:
        pass

    # Fallback
    return DEFAULT_CAL_A, DEFAULT_CAL_B, 0.0


def resample_to_energy_grid(counts, cal_a, cal_b, cal_c=0.0,
                            target_energies=CANONICAL_ENERGIES):
    """Resamples a raw-channel spectrum onto a canonical energy axis.

    Interpolates the spectrum from channel space to energy space using the
    provided calibration coefficients, preserving the total count area.

    Args:
        counts (np.ndarray): 1-D array of raw channel counts.
        cal_a (float): Calibration offset coefficient.
        cal_b (float): Calibration linear coefficient.
        cal_c (float, optional): Calibration quadratic coefficient.
            Defaults to 0.0.
        target_energies (np.ndarray, optional): 1-D array of target energy
            values in keV. Defaults to CANONICAL_ENERGIES (0–2047 keV, 1 keV/bin).

    Returns:
        np.ndarray: Resampled counts aligned with target_energies,
            area-conserving with respect to the original counts.
    """

    n_ch = len(counts)
    channels = np.arange(n_ch)
    src_energies = cal_a + cal_b * channels + cal_c * channels**2

    # Iterpolation
    interp_fn = interp1d(
        src_energies, counts,
        kind="linear",
        bounds_error=False,
        fill_value=0.0,
    )
    resampled = np.clip(interp_fn(target_energies), 0.0, None)

    # Area-conserving rescale
    src_total = counts.sum()
    tgt_total = resampled.sum()
    if tgt_total > 0 and src_total > 0:
        resampled *= src_total / tgt_total

    return resampled



def read_spectrum_file(fpath):
    """Reads a spectrum file and returns counts aligned to a canonical energy grid.

    Supports .json and .spe formats. Automatically applies energy calibration
    correction and resamples to CANONICAL_ENERGIES (0–2047 keV, 1 keV/bin).

    Args:
        fpath (str): Path to the .spe or .json spectrum file.

    Returns:
        tuple[np.ndarray, float]: A tuple containing:
            - counts (np.ndarray): Spectrum counts aligned to CANONICAL_ENERGIES.
            - t_live (float): Live time in seconds.
    """

    if fpath.endswith(".json"):
        with open(fpath) as f:
            d = json.load(f)
        raw_counts = np.array(d["data"], dtype=float)
        t_live = float(d["metadata"].get(
            "Spectrum real time (s)",
            d["metadata"].get("Spectrum live time (s)", 0)
        ))
    else:
        raw_counts = read_spec(fpath)
        t_live = read_measurement_time(fpath)

    cal_a, cal_b, cal_c = read_calibration(fpath)
    counts = resample_to_energy_grid(raw_counts, cal_a, cal_b, cal_c)

    return counts, t_live
