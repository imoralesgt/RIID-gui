import logging

# Initialize logging infrastructure
logger = logging.getLogger("spectrum_recorder")

# Official Corporate Light Theme Palette Attributes
BRAND_COLORS = {
    "primary": "#0069B4",       # IAEA Blue (Primary Focus)
    "secondary": "#333233",     # Dark Charcoal (Typography contrast)
    "accent": "#878787",        # Metallic Grey (Structural outlines)
    "bg_workspace": "#EEF1F7",  # Soft Pearl White (Workspace background canvas)
    "crimson_trace": "#B9222D"  # Trace crimson (Logarithmic counts chart color)
}

# Physical baseline default parameters (Tier-3) for detectors.json database mapping
HARDWARE_DEFAULTS = {
    "tau_d": 1.21e-6, 
    "tau_r": 0.206e-6, 
    "shaper_s_tau_pk": 2.5e-6, 
    "shaper_s_tau_pk_top": 1.0e-6,
    "vga_gain_coarse": 6.0, 
    "blr_s_threshold_gain": 3.0, 
    "smoothing_factor": 2, 
    "invert_pulse": False,
    "calib_a0": -5.90807, 
    "calib_a1": 0.953311, 
    "calib_a2": 4.16455e-05,
    "Detector type": "NaI(Tl)", 
    "Detector geometry": "Cylindrical", 
    "Detector size": "3.8 cm diameter x 3.8 cm thick", 
    "Detector type number": "38B38/SIP-E3-X2",
    "Detector serial number": "S1AA9205", 
    "Analyzer name": "NSIL-DPP4SiPM"
}
