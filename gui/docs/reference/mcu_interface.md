<!-- markdownlint-disable -->

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/mcu_interface.py#L0"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

# <kbd>module</kbd> `mcu_interface`





---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/mcu_interface.py#L234"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>function</kbd> `main`

```python
main()
```






---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/mcu_interface.py#L99"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

## <kbd>class</kbd> `ArduinoInterface`




<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/mcu_interface.py#L116"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `__init__`

```python
__init__()
```








---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/mcu_interface.py#L231"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `clear_text`

```python
clear_text()
```





---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/mcu_interface.py#L137"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `disconnect`

```python
disconnect()
```

Gracefully disconnects from the Arduino RPC router.  



---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/mcu_interface.py#L143"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `get_status`

```python
get_status()
```

Returns the status of the RPC bridge, polled at the constructor. 



**Returns:**
 
 - <b>`bool`</b>:  The status of the RPC bridge 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/mcu_interface.py#L125"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `lookup_state_idx`

```python
lookup_state_idx(state_str: str) → int
```

Reverse dictionary lookup to get the index of a status string from the `STATUS` class property. 



**Args:**
 
 - <b>`state_str`</b> (str):  The status string to lookup 



**Returns:**
 
 - <b>`int`</b>:  The index of the status 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/mcu_interface.py#L215"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `update_scroll_speed`

```python
update_scroll_speed(speed: int) → None
```

Updates the scroll speed shown in the LED matrix of the Arduino Q board. Leverages the existing RPC router instance initialized in the class constructor. 



**Args:**
 
 - <b>`speed`</b> (int):  The scroll speed to be displayed on the LED matrix 



**Returns:**
 None 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/mcu_interface.py#L152"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `update_status`

```python
update_status(status_index: int) → None
```

Updates the status shown in the onboard RGB LED of the Arduino Q board. Leverages the existing RPC router instance initialized in the class constructor. 

The `STATUS` class property is used to map the status index to a human-readable logged string. The sent value is a simple int-8 value, though. 



**Args:**
 
 - <b>`status_index`</b> (int):  The index of the status to be displayed 



**Returns:**
 None 

---

<a href="https://github.com/imoralesgt/RIID-gui/blob/main/gui/mcu_interface.py#L197"><img align="right" style="float:right;" src="https://img.shields.io/badge/-source-cccccc?style=flat-square"></a>

### <kbd>method</kbd> `update_text`

```python
update_text(text: str) → None
```

Updates the text shown in the LED matrix of the Arduino Q board. Sanitizes the string by removing non-existing characters. Leverages the existing RPC router instance initialized in the class constructor. 



**Args:**
 
 - <b>`text`</b> (str):  The text to be displayed on the LED matrix 



**Returns:**
 None 




---

_This file was automatically generated via [lazydocs](https://github.com/ml-tooling/lazydocs)._
