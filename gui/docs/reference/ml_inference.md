<!-- markdownlint-disable -->

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_inference.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `ml_inference`
On-device RIID classification: model loading, inference, and thresholds. 

:class:`MlInference` loads a compiled TFLite model from ``ml_models/``, holds the current background spectrum and trigger/classification thresholds, and runs the full background-subtraction -> preprocessing -> inference pipeline against a live spectrum. Preprocessing itself lives in ``ml_preprocessing.py``. 



---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_inference.py#L16"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `MlInference`
Contains the logic for radioisotope identification (RIID) for a raw experimental spectrum, given the environmental background and the collection time of both the experimental spectrum and the background. 

The ML model for the RIID is loaded from the `ml_models` directory.     

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_inference.py#L76"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__(
    ml_model_name: str,
    min_counts: int = 25,
    bkgnd_data: list[int] = [],
    bkgnd_live_time: float = 0.0
)
```



**Args:**
 
 - <b>`ml_model_name`</b> (str):  Name of the ML model used for inference. Models are stored in the `ml_models` directory. 
 - <b>`min_counts`</b> (int):  Minimum peak counts (after background subtraction) to perform the ML inference (counts threshold). 
 - <b>`bkgnd_data`</b> (list[int]):  List of background counts. 
 - <b>`bkgnd_live_time`</b> (float):  Live-time of the background in seconds. 




---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_inference.py#L123"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `get_bkgnd_data`

```python
get_bkgnd_data() → list[int]
```

Returns the background spectrum as a list of counts 



**Returns:**
 
 - <b>`list[int]`</b>:  List of background counts 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_inference.py#L132"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `get_bkgnd_live_time`

```python
get_bkgnd_live_time() → float
```

Returns the live-time of the background in seconds 



**Returns:**
 
 - <b>`float`</b>:  Live-time of the background in seconds 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_inference.py#L114"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `get_isotope_labels`

```python
get_isotope_labels() → dict
```

Returns the dictionary of isotope labels corresponding to the selected ML model 



**Returns:**
 
 - <b>`dict`</b>:  Dictionary of isotope labels 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_inference.py#L161"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `get_min_counts`

```python
get_min_counts() → int
```

Returns the current minimum single-channel count required to trigger ML inference - lets callers (e.g. RIIDCoreService.set_ml_model) read the operator's current setting before reconstructing this class for a different model, so it isn't silently reset to the default. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_inference.py#L274"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `inference_pipeline`

```python
inference_pipeline(spectrum_data: list[int], spectrum_live_time: float) → dict
```

Executes the ML inference pipeline for a given spectrum.   1. Subtracts the passed spectrum data from the background, normalizing background to the spectrum live-time.  2. Determines the significance of the spectrum by comparing with the threshold (limit of detection)  2.1. If there are not enough counts, ML inference is not performed  2.2. If there are enough counts, ML inference is performed  3. Returns the ML inference result in a friendly way: dictionary of classes with associated probability of occurrence 



**Args:**
 
 - <b>`spectrum_data`</b> (list[int]):  List of spectrum counts. 
 - <b>`spectrum_live_time`</b> (float):  Live-time of the spectrum in seconds. 



**Returns:**
 
 - <b>`dict | str`</b>:  STR_NOT_ENOUGH_COUNTS if there are not enough counts to perform inference. Otherwise, a dict with EVERY class label and its probability of occurrence (0.0-1.0) - not just classes above CLASSIFICATION_THRESHOLD. Callers should compare against CLASSIFICATION_THRESHOLD themselves to decide which classes count as positively detected (e.g. for a "Detected Isotopes" summary). 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_inference.py#L141"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `update_bkgnd_data`

```python
update_bkgnd_data(new_bkgnd_data: list[int], new_bkgnd_live_time: float)
```

Updates the background data and its live-time. 



**Args:**
 
 - <b>`new_bkgnd_data`</b> (list[int]):  List of background counts. 
 - <b>`new_bkgnd_live_time`</b> (float):  Live-time of the background in seconds. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_inference.py#L168"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `update_classification_threshold`

```python
update_classification_threshold(new_threshold: float)
```

Updates the multi-label classification threshold (self.CLASSIFICATION_THRESHOLD) used by callers - e.g. the GUI's RIID results panel - to decide which classes count as "detected". Does not affect inference_pipeline()'s own output, which always returns the full, unfiltered per-class probability breakdown regardless of this setting. 



**Args:**
 
 - <b>`new_threshold`</b> (float):  New threshold, clamped to [0.0, 1.0]. 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/ml_inference.py#L153"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `update_min_counts`

```python
update_min_counts(new_min_counts: int)
```

Updates the minimum count required in a single channel (after background subtraction) to trigger the ML inference. 




---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
