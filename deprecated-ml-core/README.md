
# Gamma scpectrum classificaion based on ML & Arduino Uno Q implementation


### Directory Structure

```text

├── arduinoUnoQ-spectrum/      # Project folder
│   ├── data                   
│   │    └── measDetA013.spe   # Background fallback
│   ├── inference.py           # Inference
│   ├── keras-to-tflite.ipynb  # Conversion from keras to tflite model
│   ├── mcu.cpp                
│   └── preprocessing.py       # preprocessing applied to the input                            
                                data for the different models

```
>**NOTE:** Store the spectrum files to be analyzed in data folder. It is recommended to organize files into subfolders to keep the data separate from the background file. The file `preprocessing.py` has a variable (*data_path*) that corresponds to the location of the background to be removed.

### Arduino Uno Q

#### Board Access via SSH

Connect to the board via SSH. The IP address (`192.168.1.16`) corresponds to the board's address on the local network and **may vary depending on your network configuration**.


``` bash
ssh arduino@192.168.1.16
```

#### Environment Setup

Once connected, run the following commands to set up the Python environment and install the required dependencies:

```bash
# Update package list
sudo apt update

# Install pip
sudo apt install python3-pip -y

# Create and activate a virtual environment
python3 -m venv ~/venv
source ~/venv/bin/activate

# Install dependencies
pip install ai-edge-litert --break-system-packages
pip install Pillow pyserial
pip install scikit-learn
pip install scipy
```

#### Dependencies

| Package | Description |
|---|---|
| `ai-edge-litert` | Lightweight runtime for TensorFlow Lite inference on edge devices |
| `Pillow` | Image processing library |
| `pyserial` | Serial communication with the MCU |
| `scikit-learn` | Machine learning utilities |
| `scipy` | Scientific computing tools |

> **Note:** The virtual environment must be activated each session with `source ~/venv/bin/activate` before running any Python scripts.

#### Copy Files to the Arduino Uno Q

Transfer the project folder (`arduinoUnoQ-spectrum`) to the board using `scp`:

``` bash
scp -r arduinoUnoQ-spectrum arduino@192.168.1.16:/home/arduino/
```


#### Execute the Inference

Access the board via SSH, activate the virtual environment, and run the inference script:

```bash
# Connect to the board
ssh arduino@192.168.1.16

# Activate the virtual environment
source ~/venv/bin/activate

# Go to the folder /home/arduino/arduinoUnoQ-spectrum 
cd /home/arduino/arduinoUnoQ-spectrum 

# Run inference
python3 inference.py --model models/tflite/cnn_deep.tflite --preprocess log --spectra data/data2
```

> **Note:** The `--model` flag specifies the TFLite model to use, `--preprocess` defines the preprocessing pipeline, and `--spectra` points to the input data directory.


```

<!-- 
Copy spectra folder (.spe files)
``` bash
scp -r data arduino@192.168.1.16:/home/arduino/riid
```

 Copy tflite models folder
``` bash
scp -r models/tflite arduino@192.168.1.16:/home/arduino/riid/models
```

Copy src files
``` bash
scp -r arduinoUnoQ arduino@192.168.1.16:/home/arduino/riid
``` 

**The inference script arguments may change once the final model is identified. As for now, it supports:**

| Model         | Preprocessing |
|---------------|---------------|
| `cnn_deep`    | `log`         |
| `cnn_log`     | `log`         |
| `mlp_log`     | `log`         |
| `mlp_no_log`  | `no_log`      |
| `mlp_raw`     | `raw`         |
| `roi`         | `roi`         |


