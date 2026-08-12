<!-- markdownlint-disable -->

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `view_spectrum_id`
The Spectrum ID tab: live spectrum/count-rate plots and operator controls. 

:class:`SpectrumPlotContainer` renders the live spectrum and count-rate-over- time Plotly charts, the RIID summary metric cards, and the class-probability bars. :class:`ControlPanelSidebar` renders the adjacent operator controls (model switch, visualization mode, thresholds, background record/load/save, survey start/stop). Both are backed by the shared ``RIIDCoreService`` instance and together make up the "Spectrum ID" tab built in ``main.py``. 

**Global Variables**
---------------
- **BRAND_COLORS**


---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L18"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `SpectrumPlotContainer`
Renders the live/count-rate plots, metric cards, and probability bars. 

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L29"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__(service)
```

Builds the plot container's widgets and wires them to `service`. 



**Args:**
 
 - <b>`service`</b> (RIIDCoreService):  The shared backend service instance  this container reads spectrum/state data from. 




---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L490"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_clear_cps_history`

```python
trigger_clear_cps_history()
```

Clears the count-rate plot's history and forces an immediate redraw. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L199"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_log_scale_change`

```python
trigger_log_scale_change(e)
```

Toggles the live spectrum plot between linear and log count scale. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L157"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_model_change`

```python
trigger_model_change(e)
```

Switches the active ML model. Rebuilds the class probability bars for the new model's label set on success, or reverts the dropdown to whatever's actually active if the switch failed. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L171"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_viz_mode_change`

```python
trigger_viz_mode_change(mode: str)
```

Switches between the two spectrum visualization templates - 'overlay' (background+spectrum, both traces) or 'subtracted' (single background-subtracted trace). 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L205"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `update_ui_elements`

```python
update_ui_elements()
```

Master orchestrator driving dynamic component layers stacking order and layout configurations. 


---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L792"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `ControlPanelSidebar`
The Spectrum ID tab's Survey Control Console (right-hand sidebar). 

Hosts every operator control for the live survey: ML model switch, detection threshold, hysteresis/trigger settings, background record/ load/save, and survey start/stop/clear/download. 

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L800"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__(service, plot_container: SpectrumPlotContainer)
```

Builds the sidebar's widgets. 



**Args:**
 
 - <b>`service`</b> (RIIDCoreService):  The shared backend service instance. 
 - <b>`plot_container`</b> (SpectrumPlotContainer):  The sibling plot  container, so viz-mode/log-scale changes made here can  trigger an immediate redraw there. 




---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L1069"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `open_save_bg_dialog`

```python
open_save_bg_dialog()
```

Opens the save-background dialog with a freshly-suggested filename. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L1014"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `refresh_bg_file_list`

```python
refresh_bg_file_list()
```

Repopulates the load-background dropdown from whatever's currently in data/spectra/background/ (via the service, which owns that path). 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L1110"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `refresh_widget_states`

```python
refresh_widget_states()
```

Monitors status variables and dynamically updates the panel metrics text strings. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L978"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_auto_hysteresis_toggle`

```python
trigger_auto_hysteresis_toggle(e)
```

Switches automatic mode for BOTH the ML trigger threshold and the hysteresis reset threshold together, swapping which controls are visible for each. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L1009"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_bg`

```python
trigger_bg()
```

Starts a fresh background recording for the configured duration. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L1095"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_clear`

```python
trigger_clear()
```

Wipes the accumulated survey spectrum, preserving the background. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L1100"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_download_riid`

```python
trigger_download_riid()
```

Bundles the current RIID spectrum + background into a downloadable zip. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L1021"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_load_bg`

```python
trigger_load_bg()
```

Loads the background spectrum selected in the dropdown. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L1002"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_manual_hysteresis_change`

```python
trigger_manual_hysteresis_change(e)
```

Sets the operator's manual peak-single-channel-count threshold - only takes effect while auto-reset is disabled. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L970"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_min_counts_change`

```python
trigger_min_counts_change(e)
```

Directly sets the ML pipeline's min_counts, live as the slider moves - only usable in manual mode (see trigger_auto_hysteresis_toggle), so this always takes effect immediately with no adaptation. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L1076"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_play_stop_toggle`

```python
trigger_play_stop_toggle()
```

Single control that starts a survey when idle, or halts it when running. STOP doesn't wipe the spectrum - a separate RESTART/CLEAR button (see trigger_clear) is used for that instead. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L1085"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_start`

```python
trigger_start()
```

Starts (or resumes) the continuous survey. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L1090"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_stop`

```python
trigger_stop()
```

Stops the currently running survey/recording. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_spectrum_id.py#L961"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_threshold_change`

```python
trigger_threshold_change(e)
```

Updates the multi-label classification threshold live as the slider moves - unlike the model dropdown, this is not gated to idle-only, since adjusting sensitivity on the fly during an active survey is a reasonable, useful thing to do. 




---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
