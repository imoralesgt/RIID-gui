# Spectrum Recorder CLI Utility

An automated, standalone object-oriented command-line application designed to interface with the **DPP4SiPM DAQ/MCA hardware board** to capture, track, plot, and log radiation energy spectra.

This utility is part of the `RIID-gui` workspace repository and links with the decoupled `python-api` module, which serves as the low-level backend to interact with the DAQ/MCA boards.

---

## Key Features

* **Strict Live-Time Tracking**: Polling engine loops every second to monitor actual hardware clocks (`tmr_c`), neutralizing count-rate dead-time errors.
* **Ortec `.Spe` Compliance**: Exports standard ASCII layout profiles automatically injecting custom structured detector headers.
* **Dynamic Profile Database & Auto-Registration**: Reads device digital pulse processing (DPP) settings from `detectors.json`. If a connected device serial number is unknown, the system automatically appends a new profile block with baseline defaults to the database.
* **Automated Synchronized Storage**: Saves both the spectrum data (`.spe`) and its corresponding visualization plot (`.png`) using synchronized names incorporating the hardware serial number under the `spectra/` directory.
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

### 1. Standard Collection (Automatic S/N + Timestamp Injection)
Collects a spectrum for 60 live-time seconds. It automatically detects the board's serial number, loads any existing specific parameters from the JSON profile, and outputs files using synchronized naming models:
```bash
uv run main.py --collection_time=60 --output=cs137
```
* **Output Spectrum:** `spectra/cs137_210328BEXXXXX_20260625_172000.spe`
* **Output Chart:** `spectra/cs137_210328BEXXXXX_20260625_172000.png`

### 2. Manual CLI Override Parameter Setup
Specifies explicit overriding digital pulse processing parameters via the terminal. This uses a strict 3-tier hierarchy prioritizing terminal inputs over database profiles and script fallbacks:
```bash
uv run main.py --collection_time=120 --output=co60_high_cps --no_timestamp --shaper_s_tau_pk=1.8e-6 --vga_gain_coarse=4.5
```
* **Output Spectrum:** `spectra/co60_high_cps_210328BEXXXXX.spe`
* **Output Chart:** `spectra/co60_high_cps_210328BEXXXXX.png`

### 3. Headless Performance Batch Run
Saves only the raw spectrum dataset into the `spectra/` directory while completely suppressing chart rendering on disk and preventing interactive graphical screen popups:
```bash
uv run main.py --collection_time=30 --output=headless_run --no_save_img --no_plot
```
* **Output Spectrum:** `spectra/headless_run_210328BEXXXXX_20260625_172315.spe`
* **Output Chart:** None.

### 4. Hardware Debug Output
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
* `--no_timestamp`: Disables automatic date-time strings from being injected into the file names.
* `--no_plot`: Prevents the interactive user graphical layout window from triggering upon completion.
* `--no_save_img`: Explicitly disables generating and writing the corresponding `.png` plot file to disk.
* `--verbose`: Streams live serial port interaction with the hardware (DAQ/MCA) directly into your active console screen.

### Digital Pulse Processing (DPP) Settings Matrix
*Note: If omitted from both the CLI and `detectors.json`, parameters fall back to their default values.*

* `--tau_d` `FLOAT`: Detector signal pulse shape decay constant time (s).
* `--tau_r` `FLOAT`: Detector signal pulse shape rise constant time (s).
* `--shaper_s_tau_pk` `FLOAT`: Peaking time of the slow shaper filter (s).
* `--shaper_s_tau_pk_top` `FLOAT`: Flat-top duration of the slow shaper filter (s).
* `--vga_gain_coarse` `FLOAT`: Total analog signal gain applied prior to entering the ADC stage.
* `--blr_s_threshold_gain` `FLOAT`: Slow baseline restorer noise floor tracking step multiplier.
* `--smoothing_factor` `INT`: Input moving average filtering constraint block (`1`, `2`, `4`, or `8`).

---

## Diagnostic Pipelines & Outputs

### 1. System Log File
Any runtime issue, physical communication link interruption, or unexpected uncaught runtime crash is safely trapped by the global `sys.excepthook` interceptor framework and dumped directly into **`spectrum_recorder.log`** with full tracing context blocks for field debugging support.

### 2. Hardware Log File
The DAQ/MCA API backend also dumps its log into the **daq_mca.log** file, in case a low-level hardware diagnostic is required.
