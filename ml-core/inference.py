import ai_edge_litert.interpreter as tflite
import numpy as np
import serial
import os
import time
import argparse
from preprocessing import *
from io_utils import read_spectrum_file
from sklearn.preprocessing import LabelEncoder

# Laberl encoder: associated with the classes
le = LabelEncoder()
le.fit(['bkg', 'co', 'coeu', 'cs', 'csco', 'eu'])

def inference(filename, interpreter, inp, out, preprocess_fn, mcu=None, scaler=None):
    """ 
    Predicts the isotope class for a given spectrum file.

    Args:
        filename (str): Path to the file.
        model: Keras model.
        preprocess_fn: Preprocessing function.
        le: Label encoder.
        scaler: Scaler.
        one_hot: one-hot vector.

    Returns:
        str: Predicted spectrum.

    Note: this function should be modified when connecting the acquisition pipeline and the inference, 
          unless the spectrum is first stored and then processed by the inference function.
    """

    # Check when connecting the acquisition pipeline and the inference, 
    raw_counts, t = read_spectrum_file(filename)

    counts = subtract_background(raw_counts, t)

    # Pre-processing
    x = preprocess_fn(counts).reshape(1, -1).astype(np.float32)

    if scaler is not None:
        x = scaler.transform(x)

    # Auto-reshape to match model input (handles CNNs with extra dimension automatically)
    x = x.reshape(tuple(inp['shape']))

    # Start measuring the inference time
    t0 = time.perf_counter()

    # TFLite inference
    interpreter.set_tensor(inp['index'], x)
    interpreter.invoke()

    # End measuring the inference time
    t1 = time.perf_counter()

    # Output probabilities
    probs = interpreter.get_tensor(out['index'])[0]
    
    clase_idx = int(np.argmax(probs))

    confidence = float(np.max(probs))

    # Vector one-hot
    one_hot = np.zeros(len(probs), dtype=int)
    one_hot[clase_idx] = 1

    # Total inferene time
    ms = (t1 - t0) * 1000

    # Send info to the MCU
    if mcu is not None:
        try:
            mcu.write(f"{clase_idx},{confidence:.2f}\n".encode())
        except Exception:
            pass

    label = le.inverse_transform([clase_idx])[0]
    return label, confidence, ms, probs, one_hot

def main():

    parser = argparse.ArgumentParser(description="Run TFLite inference on Arduino")
    parser.add_argument("--model", type=str, required=True, help="Path to .tflite model")
    parser.add_argument("--spectra", type=str, default="/home/arduino/arduinoUnoQ-spectrum/data", help="Path to folder containing spectrum files")
    parser.add_argument("--preprocess", type=str, default="log", choices=["log", "no_log", "raw", "roi"], help="Preprocessing method")
    parser.add_argument("--serial-port", type=str, default="/dev/ttyMSM0", help="Serial port for MCU")
    args = parser.parse_args()

    # Determine preprocessing function
    preprocess_map = {
        "log": preprocess_log,
        "no_log": preprocess_no_log,
        "raw": preprocess_baseline,
        "roi": preprocess_roi,
    }

    preprocess_fn = preprocess_map[args.preprocess]

    # Initialize TFLite model
    print(f"Loading model: {args.model}")
    interpreter = tflite.Interpreter(model_path=args.model)
    interpreter.allocate_tensors()
    inp = interpreter.get_input_details()[0]
    out = interpreter.get_output_details()[0]

    # Initialize Serial
    try:
        mcu = serial.Serial(args.serial_port, 115200, timeout=1)
    except Exception as e:
        print(f"Warning: Could not open serial port {args.serial_port} ({e}). Running without serial out.")
        mcu = None

    inference_time = []
    print(f"\n:: Processing spectra from: {args.spectra}")

    for name in sorted(os.listdir(args.spectra)):
        if not (name.lower().endswith('.spe') or name.lower().endswith('.json')):
            continue
        filepath = os.path.join(args.spectra, name)
        
        label, conf, ms, probs, one_hot = inference(filepath, interpreter, inp, out, preprocess_fn, mcu)
        inference_time.append(ms)
        
        classes = le.classes_  # ['bkg', 'co', 'coeu', 'cs', 'csco', 'eu']
        one_hot_labeled = {str(cls): int(val) for cls, val in zip(classes, one_hot)}

        print(f"{name:30s}: {label:6s} ({conf:5.1%}) | {ms:5.2f} ms | {one_hot_labeled}")
    
    if inference_time:
        print(f":: Average latency: {sum(inference_time)/len(inference_time):.2f} ms")

if __name__ == "__main__":
    main()