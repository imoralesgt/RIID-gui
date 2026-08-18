<!-- markdownlint-disable -->

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_calibration.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `view_calibration`
The Hardware & Calibration tab: instrument identity, calibration, DPP settings. 

:class:`HardwareCalibrationPanel` renders editable fields for the instrument identity, energy calibration coefficients, and advanced MCA/DPP parameters, and commits them to the hardware profile database (and optionally the board itself) on demand. 

**Global Variables**
---------------
- **BRAND_COLORS**
- **HARDWARE_DEFAULTS**


---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_calibration.py#L13"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `HardwareCalibrationPanel`
Editable instrument identity/calibration/DPP settings, keyed by board S/N. 

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_calibration.py#L16"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__(system, title_sync_callback=None, push_profile_callback=None)
```

Builds the panel's widgets. 



**Args:**
 
 - <b>`system`</b> (SpectrumAcquisitionSystem):  Owns the hardware profile  database this panel reads/writes. 
 - <b>`title_sync_callback`</b> (callable, optional):  Called after a commit  so the browser tab title can pick up any changed identity. 
 - <b>`push_profile_callback`</b> (callable, optional):  Called after a  commit to transmit the DPP parameters to the physical board. 




---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_calibration.py#L101"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `refresh_all_inputs`

```python
refresh_all_inputs()
```

Forces all input boxes to refresh to match the active hardware profile parameters. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_calibration.py#L35"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `render_layout`

```python
render_layout()
```

Builds the identity/calibration/advanced-settings fields and Commit button. 




---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
