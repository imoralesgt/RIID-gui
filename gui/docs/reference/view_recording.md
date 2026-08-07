<!-- markdownlint-disable -->

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_recording.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `view_recording`
The Spectrum Recording tab: batch acquisition with source/shielding metadata. 

:class:`SpectrumRecordingPanel` renders the radiation sources directory, shielding/absorber layer list, and the batch-recording controls/live plot for the "Spectrum Recording" tab, all backed by the shared ``RIIDCoreService`` and its ``SpectrumAcquisitionSystem``. 

**Global Variables**
---------------
- **BRAND_COLORS**


---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_recording.py#L17"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `SpectrumRecordingPanel`
Batch-recording tab: sources/shielding directories plus batch controls. 

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_recording.py#L34"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__(service)
```

Builds the panel's widgets. 



**Args:**
 
 - <b>`service`</b> (RIIDCoreService):  The shared backend service instance. 




---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_recording.py#L265"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `refresh_recording_canvas`

```python
refresh_recording_canvas(spectrum_data: list)
```

Redraws the batch spectrum plot, or an idle placeholder if empty. 



**Args:**
 
 - <b>`spectrum_data`</b> (list):  Current batch run's spectrum counts. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_recording.py#L55"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `render_layout`

```python
render_layout()
```

Assembles a dual-column wide layout splitting forms from tracking charts. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_recording.py#L191"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `sync_ui_state`

```python
sync_ui_state()
```

Pulls ongoing multi-run telemetry fields from server memory instantly upon page visibility re-attachment. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_recording.py#L184"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_batch_log_scale_change`

```python
trigger_batch_log_scale_change(e)
```

Toggles the batch plot's log/linear scale and forces a redraw. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_recording.py#L170"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_batch_start`

```python
trigger_batch_start()
```

Starts the configured multi-run batch recording. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_recording.py#L179"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `trigger_batch_stop`

```python
trigger_batch_stop()
```

Stops the currently running batch recording. 




---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
