<!-- markdownlint-disable -->

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `riid_service`
Backend service layer for the RIID station. 

Owns the DAQ hardware handle, the background/continuous-survey/batch acquisition loops, the ML inference pipeline invocation, and spectrum file I/O (SPE/JSON read-write, zip bundling, delete). The view modules (``view_spectrum_id.py``, ``view_recording.py``, ``view_download.py``, ``view_calibration.py``) all drive the UI by calling into a single shared :class:`RIIDCoreService` instance rather than touching the hardware or disk directly. 

**Global Variables**
---------------
- **SPECTRA_BATCH_DIR**
- **SPECTRA_BACKGROUND_DIR**
- **SPECTRA_RIID_DIR**


---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L29"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `RIIDCoreService`
Central hardware/service orchestration hub for the RIID station. 

Manages the lifecycle of the DAQ device handle, runs the background, continuous-survey, and batch-recording acquisition loops as asyncio tasks, invokes the ML classification pipeline on each survey tick, and handles all spectrum file I/O (SPE/JSON persistence, zip bundling for download, deletion). A single instance is constructed in ``main.py`` and shared by every view module for the lifetime of the app. 

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L134"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__(ml_model_name: str)
```

Builds the service in its idle, pre-hardware-probe state. 



**Args:**
 
 - <b>`ml_model_name`</b> (str):  Name of the ML model to load for RIID  classification (see ``ml_inference.MlInference``). Models  live under ``gui/ml_models/``. 


---

#### <kbd>property</kbd> is_batch_recording_active

True while a Spectrum Recording (batch) run is in progress. Used to disable the Spectrum ID and Hardware & Calibration tabs while true, for the same hardware-safety reasons as is_spectrum_id_active above. 

---

#### <kbd>property</kbd> is_spectrum_id_active

True while a Spectrum ID tab activity is in progress - either an active survey or a background recording (background recording is triggered from, and only meaningful within, the Spectrum ID tab's own sidebar). Used to disable the Spectrum Recording and Hardware & Calibration tabs while true, preventing the operator from launching a conflicting batch run or changing DAQ/calibration settings mid-survey (either of which could crash the hardware or corrupt the current measurement). 



---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1513"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `build_riid_download_zip`

```python
build_riid_download_zip() → tuple
```

Persists the current spectrum shown in the RIID view (self.live_spectrum) to data/spectra/riid/ - genuinely written to disk, named with the UTC timestamp of the moment this was called 
- then bundles it together with the current background spectrum, both in .json and .spe formats, into a single .zip for download. 

Only the RIID spectrum is persisted here. The background is NOT re-written to data/spectra/background/ - that already has its own explicit "Store Background Spectrum" action; re-saving it here on every RIID download would silently pile up duplicate background files. It's serialized in-memory (via a throwaway temp file, reusing the already-tested _write_spe_file logic instead of duplicating it) purely for inclusion in this zip. 



**Returns:**
 
 - <b>`(bool, str, bytes|None, str|None)`</b>:  (success, message, zip_bytes, base_filename). base_filename is the UTC-timestamped name used for both the persisted RIID files and the returned zip's contents, so the caller can name the downloaded zip consistently with what was actually saved to disk. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1799"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `build_spectra_zip`

```python
build_spectra_zip(category: str, filenames: list)
```

Bundles the requested files from a data/spectra/ category folder into an in-memory .zip archive for bulk download. 



**Args:**
 
 - <b>`category`</b> (str):  One of 'background', 'batch', 'riid'. 
 - <b>`filenames`</b> (list):  Bare filenames to include (as returned by  list_spectra_files) - basename-only, to guard against any  path-traversal attempt regardless of what the caller passes in. 



**Returns:**
 
 - <b>`bytes | None`</b>:  The zip archive's raw bytes, or None if the category is unknown, no filenames were given, or none of them existed. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1091"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `clear_cps_history`

```python
clear_cps_history()
```

Clears the count-rate plot's rolling history. Triggered by either its own dedicated Clear button OR the spectrum's own CLEAR (both are explicit "start fresh" actions) - only the automatic hysteresis-cycle buffer reset leaves the history alone, so the rate profile stays continuous across THAT event specifically. Also re-baselines both delta trackers (survey and background) and the monotonic time offset so the next sample starts fresh rather than computing a spurious delta, or plotting at a stale x-position, against pre-clear state. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1916"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `clear_survey_data`

```python
clear_survey_data()
```

Explicitly wipes the accumulated survey spectrum trace (and its associated timers/state) on operator demand. This is the ONLY path that resets the live spectrum - starting a new survey run resumes on top of it instead (see start_continuous_survey), so an explicit CLEAR is required. Works both while idle and while a survey is actively accumulating: in the latter case the running acquisition loop performs the hardware-level reset on its next tick and keeps surveying, so STOP is not required first. The background spectrum profile is intentionally left untouched. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1049"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `compute_background_subtracted_spectrum`

```python
compute_background_subtracted_spectrum(
    spectrum_data: list,
    spectrum_live_time_s: float,
    bg_data: list,
    bg_live_time_s: float
) → list
```

Reuses MLPreprocessing.subtract_background() - the exact same background subtraction step MlInference.inference_pipeline() runs before feeding a spectrum to the model - instead of maintaining a second, separate subtraction implementation in the view layer. This means the visualization is a true representation of what the classifier itself reasons over, and can't silently drift out of sync with the ML pipeline's own subtraction behavior over time. 

A fresh MLPreprocessing instance is constructed per call - this is cheap (it just stores a few int/float config values, no model loading or I/O), unlike constructing a fresh MlInference. 

min_counts=0 (not the ML pipeline's own value of 20) - this call is purely for display. The spectrum must stay visible even when the ML pipeline itself declines to run inference due to insufficient counts; min_counts here only controls a log warning inside subtract_background about the subtraction being statistically unreliable, and that warning shouldn't fire just because the operator is looking at a low-count spectrum that isn't being classified yet. 



**Args:**
 
 - <b>`spectrum_data`</b> (list):  Raw spectrum counts. 
 - <b>`spectrum_live_time_s`</b> (float):  Spectrum's live time, in SECONDS  (subtract_background expects seconds, unlike the hardware  timers elsewhere in this file which report milliseconds). 
 - <b>`bg_data`</b> (list):  Raw background counts. 
 - <b>`bg_live_time_s`</b> (float):  Background's live time, in SECONDS. 



**Returns:**
 
 - <b>`list`</b>:  Background-subtracted spectrum, negative values clipped to 0. If no usable background is available, subtract_background itself falls back to returning the raw spectrum unchanged. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1834"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `delete_spectra_files`

```python
delete_spectra_files(category: str, filenames: list) → tuple
```

Permanently deletes the requested files from a data/spectra/ category folder, for the "Delete Selected" button on the Spectra Download tab. 



**Args:**
 
 - <b>`category`</b> (str):  One of 'background', 'batch', 'riid'. 
 - <b>`filenames`</b> (list):  Bare filenames to delete - basename-only, same  path-traversal guard used by build_spectra_zip. 



**Returns:**
 
 - <b>`(bool, str)`</b>:  (success, message). success is True if at least one file was actually deleted; message summarizes the outcome, including any files that could not be found or removed. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L438"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `initialize_and_probe`

```python
initialize_and_probe()
```

Asynchronously discovers hardware on startup sequence. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1603"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `list_available_background_files`

```python
list_available_background_files() → list
```

Lists .json/.spe files available in the background spectra folder (data/spectra/background/), for the "load pre-recorded background" picker. Returns bare filenames only (no path) - the file system location stays known only to the service layer, matching how save_background_spectrum() already keeps that internal. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1763"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `list_spectra_files`

```python
list_spectra_files(category: str, ext_filter: str = 'ALL') → list
```

Lists files available for bulk download in a data/spectra/ category folder. 



**Args:**
 
 - <b>`category`</b> (str):  One of 'background', 'batch', 'riid'. 
 - <b>`ext_filter`</b> (str):  'ALL' (.json and .spe), 'JSON', or 'SPE'  (case-insensitive). 



**Returns:**
 
 - <b>`list`</b>:  Sorted bare filenames (no path) matching the filter. Empty list if the category is unknown or the folder doesn't exist yet. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1620"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `load_background_spectrum`

```python
load_background_spectrum(filename: str) → tuple
```

Loads a pre-recorded background spectrum from a .json or .spe file in data/spectra/background/, as an alternative to recording a fresh one via start_background_recording(). The current "record new" flow is untouched by this - this is purely an additional path into the same self.background_spectrum/bg_hardware_live_time_ms state. 

"Including calibration": the file's own energy calibration (offset/ linear/quadratic, as stored by _write_spe_file / _build_spectrum_metadata) is read and compared against the system's CURRENT hardware calibration. If they differ, the background is still loaded (the operator's call whether that's acceptable), but the mismatch is flagged in the returned message - since view_spectrum_id.py's _get_energy_axis() always renders the background trace using the CURRENT hw_profile calibration, a background recorded under different calibration settings would plot with a shifted/incorrect energy axis. This method does NOT overwrite the system's active calibration with the file's values - that would be a much more invasive, separate decision that this feature does not ask for. 



**Returns:**
 
 - <b>`(bool, str)`</b>:  (success, message) - the message is either a summary (potentially including a calibration-mismatch warning) or an error description for the UI to display. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L364"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `push_active_profile_to_board`

```python
push_active_profile_to_board() → bool
```

Programs the current calibration/DPP parameters onto the physical board. 

This is invoked ONLY under two conditions: 

 1. The app/service is launched for the first time (see initialize_and_probe).  2. The operator presses COMMIT CALIBRATION PARAMETERS (see view_calibration.py). 

(A hardware reconnect after a physical disconnect is treated the same as an initial probe, since the board's configuration is assumed lost on power-cycle - see _hardware_heartbeat_loop.) 

Every other acquisition entry point (survey/background/batch START) intentionally does NOT call this, so the board's on-chip spectrum accumulation is left completely undisturbed across ordinary STOP -> START cycles. 

Returns True on success, False if programming was skipped or failed. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L323"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `reinitialize_daq_handle`

```python
reinitialize_daq_handle()
```

Destroys any stale driver reference and instantiates a fresh one, transmitting the CURRENT calibration/DPP profile (tau_d, tau_r, shaper timings, VGA gain, BLR threshold, smoothing, invert-pulse) to the board via the constructor. 

IMPORTANT: this is the only place DPP parameters are ever sent to the hardware, and it must only be called from push_active_profile_to_board() - i.e. on initial hardware probe (app/service launch) or an explicit calibration commit. Routine survey/background/batch START presses must reuse the already-programmed self.daq_device handle instead of calling this, so the board's own on-chip accumulation registers are never disturbed by a config resend. 

The timers_preset is fixed at the unsigned-32-bit ceiling (effectively unlimited) for every operation - background and batch recordings already enforce their own exact duration purely in software by polling elapsed hardware live-time, so no per-operation preset needs to be (re)programmed here. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1438"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `save_background_spectrum`

```python
save_background_spectrum(
    filename: str,
    save_json: bool = True,
    save_spe: bool = True
) → tuple[bool, str]
```

Persists the latest recorded background spectrum to disk, in JSON and/or SPE format as requested. Reuses the exact same _build_spectrum_metadata()/_write_spe_file() pipeline as batch recordings instead of duplicating any serialization logic, so detector/calibration/source metadata is included identically to how batch spectra files are stored. 

"Material type" is forced to "background" on a COPY of the metadata used for this save only - the live runtime_metadata dict (used elsewhere for batch/sources) is left untouched. 



**Args:**
 
 - <b>`filename`</b> (str):  Desired base filename (without extension), as  chosen by the operator in the save prompt. 
 - <b>`save_json`</b> (bool):  Whether to write the .json file. 
 - <b>`save_spe`</b> (bool):  Whether to write the .spe file. 



**Returns:**
 
 - <b>`(bool, str)`</b>:  (success, message) - message is a short summary of what was saved, or an error description for the UI to display. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L985"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `set_auto_hysteresis_enabled`

```python
set_auto_hysteresis_enabled(enabled: bool)
```

Toggles automatic mode for BOTH the hysteresis reset threshold and the ML trigger threshold (min_counts) together - called by the GUI's "Automatic hysteresis" checkbox. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L999"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `set_manual_hysteresis_threshold`

```python
set_manual_hysteresis_threshold(new_threshold: int)
```

Sets the operator's manual peak-single-channel-count threshold, used only while auto_hysteresis_enabled is False. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L968"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `set_ml_classification_threshold`

```python
set_ml_classification_threshold(new_threshold: float)
```

Passthrough to MlInference.update_classification_threshold() - the entry point the GUI's Detection Threshold slider calls, so the view layer doesn't need to reach into self.ml_inference directly. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L975"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `set_ml_min_counts`

```python
set_ml_min_counts(new_min_counts: int)
```

Directly sets MlInference's min_counts, called by the GUI's ML trigger slider - only ever shown/usable in manual mode (see auto_hysteresis_enabled), so this always applies immediately with no adaptation. In auto mode, the poll loop recomputes and applies the effective value itself every tick instead (see _compute_effective_ml_min_counts), and this slider isn't shown at all. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1004"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `set_ml_model`

```python
set_ml_model(model_name: str) → tuple
```

Swaps the active ML model at runtime (cnn_multilabel / cnn_deep). Reconstructs self.ml_inference with the new model, since MlInference doesn't support hot-swapping its underlying model file - but carries the current background data, classification threshold, and minimum-counts trigger over to the new instance, so switching models doesn't silently reset any of those. 

Only meaningful while idle - the model choice affects what _execute_ml_pipeline() returns (including the label SET itself, since cnn_deep and cnn_multilabel have different classes), so switching mid-survey could produce a confusing mix of old- and new-model results. The GUI is expected to only enable this control while stopped, but this method also guards defensively. 



**Returns:**
 
 - <b>`(bool, str)`</b>:  (success, message) for the UI to display. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L314"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `set_state`

```python
set_state(state_string: str) → None
```





---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L490"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `start_background_recording`

```python
start_background_recording(target_time: int)
```

Spawns background spectrum profiling worker task and purges stale arrays. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1205"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `start_batch_recording`

```python
start_batch_recording(target_time: int, total_runs: int, prefix: str)
```

Assembles automated structural script loops mapping data files. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L638"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `start_continuous_survey`

```python
start_continuous_survey()
```

Launches/resumes continuous acquisition on the already-programmed device handle. Does NOT resend DPP parameters - true continuity across STOP -> START cycles is achieved by leaving the board's configuration untouched on an ordinary start. DPP parameters are only ever transmitted by push_active_profile_to_board() (hardware probe / an explicit calibration commit). 

Per the DPP4SiPM firmware docs, the $AQ start command (flags 0/1) unavoidably clears the BRAM spectrum memory as part of starting acquisition - there is no hardware "resume" flag. _continuous_survey_sequence() compensates for this in software by carrying the previously accumulated spectrum forward and adding each new hardware reading on top of it. The live-time timer is NOT reset by $AQ 1 (only an explicit $AQ 4 / timers_reset() does that, which ordinary START never calls), so it already persists correctly without any extra bookkeeping. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L455"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `start_service_loops`

```python
start_service_loops()
```

Spawns long-running async background monitor workers. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1877"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `stop_execution`

```python
stop_execution()
```

Halts the active acquisition loop without discarding the collected spectrum. The last spectrum trace and identification result are left exactly as they were so the operator can still review what was captured before pressing STOP. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/riid_service.py#L1963"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `verify_runtime_hardware_safety`

```python
verify_runtime_hardware_safety() → bool
```

Validates live connectivity during active data collection runs. Auto-halts on failure. 




---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
