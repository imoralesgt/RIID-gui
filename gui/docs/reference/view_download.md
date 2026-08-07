<!-- markdownlint-disable -->

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_download.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `view_download`
The Spectra Download tab: bulk file management for recorded spectra. 

:class:`SpectraDownloadPanel` renders one sub-tab per category (Background, Batch, RIID); each sub-tab is a :class:`_CategoryDownloadSection` handling that category's file picker, multi-select download, and delete. 

**Global Variables**
---------------
- **BRAND_COLORS**


---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_download.py#L13"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `SpectraDownloadPanel`
Lets the operator bulk-download recorded spectra files from any of the three data/spectra/ subfolders (background, batch, riid), each in its own tab with a "select all" checkbox and an extension filter. 

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_download.py#L25"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__(service)
```

Builds the panel's per-category tabs. 



**Args:**
 
 - <b>`service`</b> (RIIDCoreService):  The shared backend service instance. 




---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/view_download.py#L35"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `render_layout`

```python
render_layout()
```

Builds the category tab bar and one `_CategoryDownloadSection` per tab. 




---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
