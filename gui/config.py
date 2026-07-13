import os
import logging
import sys
import threading

# 1. Base File System Directory and Root Log Path Mapping
DATA_DIR = "data"
LOG_FILENAME = "gui.log"
LOG_FILE_PATH = LOG_FILENAME  # Targeted at the structural workspace root folder

os.makedirs(DATA_DIR, exist_ok=True)

# 2. CLEAR ALL PRE-EXISTING implicit logger handlers to bypass root blocking traps
root_logger = logging.getLogger()
if root_logger.handlers:
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

# Configure the global root capturing scope wide open to receive records
root_logger.setLevel(logging.INFO)

# Structured layout format mapping explicit thread source contexts
log_formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)s] (%(threadName)s) [%(name)s]: %(message)s"
)

# Create and configure the synchronous Standard Out streaming line
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(log_formatter)
root_logger.addHandler(console_handler)

# Create and configure the absolute continuous file writing line (gui.log)
file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
file_handler.setFormatter(log_formatter)
root_logger.addHandler(file_handler)

# Allocate master application pointer instance
logger = logging.getLogger("spectrum_recorder")
logger.info(f"Master root file logger successfully established. File location: {os.path.abspath(LOG_FILE_PATH)}")

# =========================================================================
# FIXED: DEEP NOISE FILTERING MATRIX
# =========================================================================
# Forcefully mute the third-party file watcher library flooding the outputs
logging.getLogger("watchfiles").setLevel(logging.WARNING)
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)

# If nicegui or any other underlying component starts flooding, we can filter them similarly:
logging.getLogger("nicegui").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.WARNING)

# Ensure the DAQ MCA API logger continues to report its diagnostic messages safely
logging.getLogger("DAQ_MCA_API").setLevel(logging.INFO)
# =========================================================================

# 3. UNHANDLED ASYNCHRONOUS EXCEPTION TRACKING INTERCEPTORS
def global_unhandled_exception_hook(exctype, value, traceback):
    if issubclass(exctype, KeyboardInterrupt):
        sys.__excepthook__(exctype, value, traceback)
        return
    logger.critical("!!! CRITICAL UNHANDLED MAIN THREAD EXCEPTION ENCOUNTERED !!!", exc_info=(exctype, value, traceback))

def global_thread_exception_hook(args):
    logger.critical(
        f"!!! CRITICAL UNHANDLED BACKGROUND WORKER EXCEPTION IN THREAD [{args.thread.name}] !!!", 
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
    )

sys.excepthook = global_unhandled_exception_hook
threading.excepthook = global_thread_exception_hook
logger.info("Global multi-threaded exception intercept handlers bound to system environment.")
# 4. Official IAEA Light Theme Palette Attributes
BRAND_COLORS = {
    "primary": "#0069B4",       # IAEA Blue (Primary Focus)
    "secondary": "#333233",     # Dark Charcoal (Typography contrast)
    "accent": "#878787",        # Metallic Grey (Structural outlines)
    "bg_workspace": "#EEF1F7",  # Soft Pearl White (Workspace background canvas)
    "crimson_trace": "#B9222D", # Trace crimson (Logarithmic counts chart color)
    
    # Centralized plot aesthetics keys to clean up hardcoded values
    "plot_grid": "#E5E7EB",     # Light Grey for canvas grid lines
    "plot_bg": "#FFFFFF",       # Pure white for chart plotting backgrounds
    "plot_paper": "#FFFFFF",    # Pure white for surrounding card papers
    "legend_bg": "#FFFFFF"      # Base color for overlay cards
}

def get_rgba_fill(color_key: str, alpha: float = 0.15) -> str:
    """Dynamically parses a hex key straight from BRAND_COLORS into a transparent RGBA string."""
    hex_val = BRAND_COLORS.get(color_key, "#878787").lstrip('#')
    try:
        r = int(hex_val[0:2], 16)
        g = int(hex_val[2:4], 16)
        b = int(hex_val[4:6], 16)
        return f"rgba({r}, {g}, {b}, {alpha})"
    except Exception as e:
        logger.error(f"[COLOR_SYSTEM] Failed to convert hex code '{hex_val}': {e}")
        return f"rgba(135, 135, 135, {alpha})"

DETECTORS_DB_FILENAME = "detectors.json"
SOURCES_DB_FILENAME = "sources.json"

DETECTORS_DB_PATH = os.path.join(DATA_DIR, DETECTORS_DB_FILENAME)
SOURCES_DB_PATH = os.path.join(DATA_DIR, SOURCES_DB_FILENAME)

HARDWARE_DEFAULTS = {
    "SYS-ID": "SYS-STANDBY",  
    "tau_d": 1.21e-6, 
    "tau_r": 0.206e-6, 
    "shaper_s_tau_pk": 2.5e-6, 
    "shaper_s_tau_pk_top": 1.0e-6,
    "vga_gain_coarse": 6.0, 
    "blr_s_threshold_gain": 4.0, 
    "smoothing_factor": 2, 
    "invert_pulse": False,
    "calib_a0": 0, 
    "calib_a1": 1, 
    "calib_a2": 0,
    "Detector type": "NaI(Tl)", 
    "Detector geometry": "Cylindrical", 
    "Detector size": "3.8 cm diameter x 3.8 cm thick", 
    "Detector type number": "38B38/SIP-E3-X2",
    "Detector serial number": "UNKNOWN", 
    "Analyzer name": "NSIL-DPP4SiPM"
}
