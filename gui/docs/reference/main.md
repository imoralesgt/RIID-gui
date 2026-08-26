<!-- markdownlint-disable -->

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/main.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `main`
Application entry point: NiceGUI page shell and top-level app wiring. 

Instantiates the shared :class:`~riid_service.RIIDCoreService` backend singleton, registers the app-startup hardware probe, and builds the four-tab station UI (:class:`RIIDSpectroscopyApp`) served at the root ``/`` route. Run directly with ``uv run main.py`` (see the repository README). 

**Global Variables**
---------------
- **BRAND_COLORS**
- **ML_MODEL_NAME**

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/main.py#L45"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `runtime_bootstrap_sequence`

```python
runtime_bootstrap_sequence()
```

App-startup hook: probes for hardware and starts the background service loops. 


---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/main.py#L383"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `index`

```python
index()
```

Serves the station UI at the root route - one fresh app instance per client. 


---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/main.py#L57"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `RIIDSpectroscopyApp`
The top-level four-tab station UI, one instance per connected browser client. 

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/main.py#L60"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__()
```

Builds the workspace, sets the initial tab title, and starts the UI sync timer. 




---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/main.py#L180"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `build_workspace`

```python
build_workspace()
```

Constructs the visual container tree utilizing official palettes. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/main.py#L272"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `global_ui_sync_tick`

```python
global_ui_sync_tick()
```

Drives all real-time component updates and handles dynamic layout changes. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/main.py#L108"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `update_browser_tab_title`

```python
update_browser_tab_title()
```

Updates the actual browser tab title text dynamically based on profile records. 




---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
