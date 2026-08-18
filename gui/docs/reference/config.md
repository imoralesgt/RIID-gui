<!-- markdownlint-disable -->

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/config.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `config`
App-wide constants, filesystem layout, logging setup, and brand palette. 

Imported by every other module in this package for shared configuration: data directory paths, the ``logger`` instance, ``BRAND_COLORS``, and ``HARDWARE_DEFAULTS``. Executes its logging/exception-hook setup once, at first import. 

**Global Variables**
---------------
- **DATA_DIR**
- **CONF_DIR**
- **SPECTRA_DIR**
- **SPECTRA_BACKGROUND_DIR**
- **SPECTRA_BATCH_DIR**
- **SPECTRA_RIID_DIR**
- **LOG_FILENAME**
- **LOG_FILE_PATH**
- **BRAND_COLORS**
- **DETECTORS_DB_FILENAME**
- **SOURCES_DB_FILENAME**
- **DETECTORS_DB_PATH**
- **SOURCES_DB_PATH**
- **HARDWARE_DEFAULTS**
- **WIFI_DB_FILENAME**
- **WIFI_DB_PATH**
- **WIFI_DEFAULTS**
- **WIFI_SOCKET_PATH**

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/config.py#L83"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `global_unhandled_exception_hook`

```python
global_unhandled_exception_hook(exctype, value, traceback)
```

Logs any otherwise-unhandled main-thread exception before the process exits. 


---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/config.py#L90"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `global_thread_exception_hook`

```python
global_thread_exception_hook(args)
```

Logs any otherwise-unhandled exception raised in a background worker thread. 


---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/config.py#L116"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `get_rgba_fill`

```python
get_rgba_fill(color_key: str, alpha: float = 0.15) → str
```

Dynamically parses a hex key straight from BRAND_COLORS into a transparent RGBA string. 




---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
