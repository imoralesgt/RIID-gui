<!-- markdownlint-disable -->

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_preprocessing.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `ml_preprocessing`
Spectrum preprocessing utilities feeding the RIID ML pipeline. 

:class:`MLPreprocessing` implements the feature pipeline the classifier was trained on: background subtraction, log10 scaling, Savitzky-Golay smoothing, decimation, and area normalization. Used directly by ``ml_inference.MlInference`` and by ``RIIDCoreService`` for the "Spectrum - Background" visualization. 



---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_preprocessing.py#L14"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `MLPreprocessing`
Background subtraction and log10/smoothing/decimation feature pipeline. 

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_preprocessing.py#L17"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__(
    min_counts: int = 25,
    crop_bins_lld: int = 50,
    decimation: int = 8,
    sg_window_length: int = 11,
    sg_polyorder: int = 3
)
```



**Args:**
 
 - <b>`min_counts`</b> (int, optional):  Recommended minimum counts threshold for background subtraction. Defaults to 25. 
 - <b>`crop_bins_lld`</b> (int, optional):  Number of low-energy bins (LLD) to crop. Defaults to 50. 
 - <b>`decimation`</b> (int, optional):  Decimation factor. Defaults to 8. 
 - <b>`sg_window_length`</b> (int, optional):  Window length for Savitzky-Golay filter. Expected 5 or larger. Defaults to 11. 
 - <b>`sg_polyorder`</b> (int, optional):  Polynomial order for Savitzky-Golay filter. Expected 3 or larger. Defaults to 3. 




---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_preprocessing.py#L40"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `get_crop_bints_lld`

```python
get_crop_bints_lld()
```

Returns the number of low-energy (LLD) bins cropped before inference. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_preprocessing.py#L44"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `get_decimation`

```python
get_decimation()
```

Returns the configured decimation factor. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_preprocessing.py#L36"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `get_min_counts`

```python
get_min_counts()
```

Returns the configured minimum-counts threshold. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_preprocessing.py#L90"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `preprocess_log10`

```python
preprocess_log10(spectrum_data: ndarray) → ndarray
```

Applies log10 scaling, smoothing, decimation, and normalization to a given spectrum. 

Uses the class attributes defined in the constructor for configuration: 


- crop_bins_lld: how many low-energy bins to crop 
- decimation: decimation factor 
- sg_window_length: window length for Savitzky-Golay filter 
- sg_polyorder: polynomial order for Savitzky-Golay filter 



**Args:**
 
 - <b>`spectrum_data`</b> (np.ndarray):  Raw spectrum counts. 



**Returns:**
 
 - <b>`np.ndarray`</b>:  Normalized, decimated, filtered, and log10-scaled spectrum 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_preprocessing.py#L125"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `preprocess_pipeline`

```python
preprocess_pipeline(
    spectrum_data: list[int],
    spectrum_live_time: float,
    bkgnd_data: list[int] = [],
    bkgnd_live_time: float = 0.0
) → ndarray
```

Executes the entire preprocessing pipeline, including background subtraction, log10 scaling, smoothing, decimation, and normalization. 



**Args:**
 
 - <b>`spectrum_data`</b> (list[int]):  List of spectrum counts. 
 - <b>`spectrum_live_time`</b> (float):  Live-time of the spectrum in seconds. 
 - <b>`bkgnd_data`</b> (list[int], optional):  List of background counts. Defaults to []. 
 - <b>`bkgnd_live_time`</b> (float, optional):  Live-time of the background in seconds. Defaults to 0.0. 



**Returns:**
 
 - <b>`np.ndarray`</b>:  Normalized, decimated, filtered, and log10-scaled spectrum 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_preprocessing.py#L48"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `subtract_background`

```python
subtract_background(
    spectrum_data: list[int],
    spectrum_live_time: float,
    bkgnd_data: list[int] = [],
    bkgnd_live_time: float = 0.0
) → ndarray
```

Subtracts the passed spectrum data from the background, normalizing background to the spectrum live-time. 



**Args:**
 
 - <b>`spectrum_data`</b> (list[int]):  List of spectrum counts. 
 - <b>`spectrum_live_time`</b> (float):  Live-time of the spectrum in seconds. 
 - <b>`bkgnd_data`</b> (list[int], optional):  List of background counts. Defaults to []. 
 - <b>`bkgnd_live_time`</b> (float, optional):  Live-time of the background in seconds. Defaults to 0.0. 



**Returns:**
 
 - <b>`np.ndarray`</b>:  Background-subtracted spectrum with negative values clipped to zero. 




---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
