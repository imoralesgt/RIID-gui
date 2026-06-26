# Spectrum Recorder CLI Utility

An automated, standalone object-oriented command-line application designed to interface with the **DPP4SiPM DAQ/MCA hardware board** to capture, track, plot, and log radiation energy spectra.

This utility is part of the `RIID-gui` workspace repository and links with the decoupled `python-api` module, which serves as the low-level backend to interact with the DAQ/MCA boards over a UART serial connection.

---

## Key Features

* **Strict Live-Time Tracking**: Polling engine loops every second to monitor actual hardware clocks (`tmr_c`), neutralizing count-rate dead-time errors.
* **Ortec `.Spe` Compliance**: Exports standard ASCII layout profiles automatically injecting custom structured detector headers and energy calibration coefficients ($MCA_CAL).
* **Dynamic Profile Database & Auto-Registration**: Reads device digital pulse processing (DPP) settings and energy calibration factors from `detectors.json`. If a connected device serial number is unknown, the system automatically appends a new profile block with baseline defaults to the database.
* **Sequential Batch Recording (N Runs)**: Supports capturing a sequential series of spectra within a single call. Batch runs freeze the initial call timestamp across all generated datasets to maintain group continuity.
* **Automated Headless Storage**: By default, saves both the spectrum data (`.spe`) and its corresponding visualization plot (`.png`) silently under the `spectra/` directory. Interactive popups are disabled by default to support remote or automated lab execution.
* **Localized Dual-Pipe Logging**: Saves background debug stack traces to a rolling file engine (`spectrum_recorder.log`) while keeping the primary terminal clean.
* **Native UV Workspace System**: Fully integrated with the native package management workspace layout for zero-configuration editable installs.

---

## Installation & Environment Setup

This utility relies on **`uv`** to build its package environment structure. Ensure you initialize the global layout workspace before running.

### 1. Configure the Workspace Root
Verify that your top-level repository file (`~/Gits/RIID-gui/pyproject.toml`) registers both members correctly:

```toml
[project]
name = "riid-gui-workspace"
version = "0.1.0"
requires-python = ">=3.12"

[tool.uv]
package = false

[tool.uv.workspace]
members = [
    "utils/spectrum_recorder",
    "daq-core/NSIL-MCA-DPP4SiPM/sw/python-api"
]
```

### 2. Synchronize Dependencies
Navigate to the root directory of the repository and execute the compilation step:

```bash
cd ~/Gits/RIID-gui
uv sync
```
This automatically links the `core` modules of the underlying `python-api` package editably inside the local `.venv` environment.

---

## CLI Usage Examples

Always execute commands using `uv run` inside the `utils/spectrum_recorder` directory:

```bash
cd utils/spectrum_recorder
```

### 1. Standard Collection (Headless Storage by Default)
Collects a single spectrum for 60 live-time seconds. It automatically detects the board's serial number, loads settings and calibration coefficients from the JSON database profile, and writes files directly to the storage folder without flashing any display windows:
```bash
uv run main.py --collection_time=60 --output=cs137
```
* **Output Spectrum:** `spectra/cs137_210328BE437AB_20260625_172000.spe`
* **Output Chart:** `spectra/cs137_210328BE437AB_20260625_172000.png`

### 2. Batch Sequential Run with Shared Session Timestamps
Collects a sequence series of 3 spectra automatically within a single call. All generated files are tracked with a sequence string index (`runXX`) and share the exact same starting timestamp:
```bash
uv run main.py --collection_time=30 -n 3 --output=decay_series
```
* **Output Files (Run 1):** `spectra/decay_series_210328BE437AB_run01_20260625_174012.spe` (and `.png`)
* **Output Files (Run 2):** `spectra/decay_series_210328BE437AB_run02_20260625_174012.spe` (and `.png`)
* **Output Files (Run 3):** `spectra/decay_series_210328BE437AB_run03_20260625_174012.spe` (and `.png`)

### 3. Injecting Custom Energy Calibration via CLI
Allows overruling the local database constants dynamically through the console command for rapid energy characterization checks without sending these math properties to the physical DPP board registers:
```bash
uv run main.py --collection_time=60 --output=calib_run --calib_a0=-10.25 --calib_a1=0.355 --calib_a2=0.00001
```

### 4. Displaying Interactive Visualization Plots
If you want to visually verify the captured photopeaks on screen upon session completion, pass the explicit plotting flag:
```bash
uv run main.py --collection_time=60 --output=peak_check --show_plot
```

### 5. Hardware Debug Output Telemetry
Launches the tracking sequence displaying a live terminal view of the underlying hardware register ticks second by second:
```bash
uv run main.py --collection_time=10 --verbose
```

---

## Command-Line Arguments Reference

You can review all parameters natively at any time by triggering the help menu flag:
```bash
uv run main.py --help
```

### Core Application Flags
* `--collection_time` `INT` (**Mandatory**): Total target collection window specified in live-time seconds.
* `--output` `STR` (Default: `"spectrum"`): Base file prefix. Files are stored inside the `spectra/` directory.
* `-n`, `--spectra_count` `INT` (Default: `1`): Number of sequential spectra (N) to record automatically.
* `--no_timestamp`: Disables automatic date-time strings from being injected into the file names.
* `--show_plot`: Enables displaying the interactive graphic window upon completion (Disabled by default).
* `--no_save_img`: Explicitly disables generating and writing the corresponding `.png` plot file to disk.
* `--verbose`: Streams live serial port interaction with the hardware (DAQ/MCA) directly into your active console screen.

### Digital Pulse Processing (DPP) Settings Matrix
*Note: If omitted from both the CLI parameters and `detectors.json`, settings fall back to their baseline default values.*

* `--tau_d` `FLOAT`: Detector signal pulse shape decay constant time (s).
* `--tau_r` `FLOAT`: Detector signal pulse shape rise constant time (s).
* `--shaper_s_tau_pk` `FLOAT`: Peaking time of the slow shaper filter (s).
* `--shaper_s_tau_pk_top` `FLOAT`: Flat-top duration of the slow shaper filter (s).
* `--vga_gain_coarse` `FLOAT`: Total analog signal gain applied prior to entering the ADC stage.
* `--blr_s_threshold_gain` `FLOAT`: Slow baseline restorer noise floor tracking step multiplier.
* `--smoothing_factor` `INT`: Input moving average filtering constraint block (`1`, `2`, `4`, or `8`).

### Off-Board Software Calibration Parameters
*Note: These factors are only injected into the exported spectrum file metadata and are not written to the DAQ/MCA board.*

* `--calib_a0` `FLOAT` (Default: `0.0`): Calibration coefficient a0 (Channel-to-Energy Offset block).
* `--calib_a1` `FLOAT` (Default: `1.0`): Calibration coefficient a1 (Channel-to-Energy Linear block).
* `--calib_a2` `FLOAT` (Default: `2.0`): Calibration coefficient a2 (Channel-to-Energy Quadratic block).

---

## Diagnostic Pipelines & Outputs

### 1. System Log File
Any runtime issue, physical communication link interruption, or unexpected uncaught runtime crash is safely trapped by the global `sys.excepthook` interceptor framework and dumped directly into **`spectrum_recorder.log`** with full tracing context blocks for field debugging support.

### 2. Hardware Log File
The DAQ/MCA API backend also dumps its log into the **`daq_mca.log`** file, in case a low-level hardware diagnostic is required.
