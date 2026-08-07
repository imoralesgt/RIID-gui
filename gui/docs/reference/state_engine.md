<!-- markdownlint-disable -->

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/state_engine.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `state_engine`
Persistence layer for hardware/source JSON databases and device discovery. 

:class:`SpectrumAcquisitionSystem` owns the on-disk hardware calibration profile database (``detectors.json``) and radiation source library (``sources.json``), the active hardware profile derived from them, and the low-level DAQ device probe used to identify a connected board by serial number. Instantiated once by ``RIIDCoreService``. 

**Global Variables**
---------------
- **HARDWARE_DEFAULTS**
- **DETECTORS_DB_PATH**
- **SOURCES_DB_PATH**


---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/state_engine.py#L16"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `SpectrumAcquisitionSystem`
Owns the hardware/source JSON databases and the active hardware profile. 

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/state_engine.py#L19"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__(
    json_path: str = 'data/conf/detectors.json',
    sources_path: str = 'data/conf/sources.json'
)
```

Loads the hardware and source databases from disk. 



**Args:**
 
 - <b>`json_path`</b> (str):  Path to the hardware calibration profile  database (keyed by board serial number). 
 - <b>`sources_path`</b> (str):  Path to the radiation source library  database. 




---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/state_engine.py#L88"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `probe_device`

```python
probe_device() → str
```

Opens a connection to whatever DAQ board is present and identifies it. 

Registers a fresh default hardware profile for a never-before-seen serial number, then syncs `hw_profile` to match. 



**Returns:**
 
 - <b>`str`</b>:  The discovered board's serial number. 



**Raises:**
 
 - <b>`Exception`</b>:  If no board could be opened/identified. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/state_engine.py#L56"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `save_hardware_db`

```python
save_hardware_db() → bool
```

Writes the in-memory hardware profile database to disk. 



**Returns:**
 
 - <b>`bool`</b>:  True on success, False if the write failed. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/state_engine.py#L72"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `save_sources_db`

```python
save_sources_db() → bool
```

Writes the in-memory radiation source library database to disk. 



**Returns:**
 
 - <b>`bool`</b>:  True on success, False if the write failed. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/state_engine.py#L116"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `sync_hardware_profile`

```python
sync_hardware_profile() → None
```

Rebuilds `hw_profile` from the current serial number's saved values, falling back to `HARDWARE_DEFAULTS` for any key not yet persisted. 




---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
