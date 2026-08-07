"""Renders landscape 3-D "stacked block" architecture diagrams for every
production RIID model in gui/ml_models/*.tflite into docs/res/.

Unlike a hand-maintained model definition, the layer sequence (Conv1D
filters/kernel sizes, MaxPooling1D pool sizes, Dense units, ReLU/softmax/
sigmoid activations) is extracted directly from each .tflite file's op
graph via ai_edge_litert - see extract_architecture() below - so this stays
correct automatically if a model is retrained or a new one is dropped into
ml_models/, with nothing here to update by hand. The extracted architecture
is rebuilt as a throwaway (never-trained) Keras model purely so visualkeras
has something to draw; no weights from the real models are used or needed,
since only the layer structure matters for this diagram.

Run from the gui/ directory with the `viz` dependency group installed:

    uv sync --group viz
    uv run --group viz python docs/scripts/render_architecture_diagrams.py

visualkeras only supports the legacy (Keras 2) layer API, hence the
TF_USE_LEGACY_KERAS env var below - it must be set before `tensorflow` is
first imported.
"""

import os

os.environ.setdefault("TF_USE_LEGACY_KERAS", "1")

from pathlib import Path
from collections import defaultdict

import ai_edge_litert.interpreter as tflite
import tensorflow as tf
import visualkeras
from PIL import Image, ImageFont

REPO_ROOT = Path(__file__).resolve().parents[3]
MODELS_DIR = REPO_ROOT / "gui" / "ml_models"
OUTPUT_DIR = REPO_ROOT / "docs" / "res"

# visualkeras' `padding` param only offsets the horizontal start position -
# the diagonal "roof" of the tallest box is drawn starting at y=0 with no
# vertical margin at all, so it gets clipped right at the top of the
# generated image regardless of `padding`. Worked around below by rendering
# in-memory and pasting onto a taller canvas with real top margin added.
TOP_MARGIN_PX = 40

Conv1D = tf.keras.layers.Conv1D
MaxPooling1D = tf.keras.layers.MaxPooling1D
Flatten = tf.keras.layers.Flatten
Dense = tf.keras.layers.Dense


class HeadSigmoid(Dense):
    """Tags a model's final independent-per-class (sigmoid) layer with its
    own type, purely so visualkeras can color/legend it separately from a
    plain hidden Dense layer."""


class HeadSoftmax(Dense):
    """Tags a model's final mutually-exclusive-classes (softmax) layer with
    its own type, purely so visualkeras can color/legend it separately from
    a plain hidden Dense layer."""


# IAEA visual identity palette (matches gui/config.py's BRAND_COLORS, plus
# the wider secondary palette from the official brand guide) - outline uses
# the brand's dark charcoal uniformly rather than a per-color shade.
_OUTLINE = "#333233"
COLOR_MAP = defaultdict(dict, {
    Conv1D: {"fill": "#0069B4", "outline": _OUTLINE},       # IAEA Blue (primary)
    MaxPooling1D: {"fill": "#8ECBF9", "outline": _OUTLINE}, # light blue (secondary)
    Flatten: {"fill": "#878787", "outline": _OUTLINE},      # gray (primary)
    Dense: {"fill": "#C8B485", "outline": _OUTLINE},        # tan (secondary)
    HeadSigmoid: {"fill": "#ED692E", "outline": _OUTLINE},  # orange (secondary)
    HeadSoftmax: {"fill": "#413F8F", "outline": _OUTLINE},  # indigo (secondary)
})


def _spatial_length(shape) -> int:
    """Returns the length ("time"/energy-channel) dimension of a (batch,
    length, channels) or (batch, 1, length, channels) tensor shape - i.e.
    everything except the batch dim, the trailing channel dim, and any
    dummy size-1 axis in between."""
    dims = [int(d) for d in shape[1:-1]]
    dims = [d for d in dims if d != 1] or [1]
    return dims[-1]


def extract_architecture(tflite_path: Path):
    """Reconstructs the conceptual layer sequence of a compiled .tflite
    model by walking its actual op graph (not a hand-maintained copy of the
    architecture).

    Keras Conv1D/MaxPooling1D get lowered by the TFLite converter into 2-D
    ops (CONV_2D/MAX_POOL_2D) bracketed by EXPAND_DIMS/RESHAPE plumbing to
    add/remove a dummy axis - those plumbing ops are skipped entirely here;
    only CONV_2D, MAX_POOL_2D, FULLY_CONNECTED, and the trailing
    SOFTMAX/LOGISTIC activation are treated as real layers. A Flatten is
    inserted wherever a FULLY_CONNECTED immediately follows a conv/pool
    layer, matching how the original Keras model would have needed one.

    Relies on `Interpreter._get_ops_details()`, an underscore-prefixed
    (unofficial) ai_edge_litert API - if a future version removes it, this
    will need an alternative way to enumerate ops.

    Returns:
        (input_shape, layers): `input_shape` is the model's raw input
        tensor shape (e.g. [1, 250, 1]). `layers` is an ordered list of
        dicts, each `{"kind": "conv" | "pool" | "flatten" | "dense", ...}`
        with kind-specific keys (filters/kernel_size/padding/relu for
        "conv"; pool_size for "pool"; units/relu/head_activation for
        "dense" - head_activation is only present on the final classifier
        layer, set to "softmax" or "sigmoid").
    """
    interp = tflite.Interpreter(model_path=str(tflite_path))
    interp.allocate_tensors()
    ops = interp._get_ops_details()
    tensors = {t["index"]: t for t in interp.get_tensor_details()}
    input_shape = interp.get_input_details()[0]["shape"]

    layers = []
    current_length = _spatial_length(input_shape)
    prev_kind = None

    for i, op in enumerate(ops):
        name = op["op_name"]

        if name == "CONV_2D":
            # CONV_2D's own raw output tensor already carries the true
            # post-bias/activation shape (Keras Conv1D gets lowered to a 4-D
            # CONV_2D bracketed by EXPAND_DIMS/RESHAPE plumbing, but that
            # plumbing only adds/removes a dummy size-1 axis around THIS
            # tensor - it never changes the length/channel values
            # themselves) - no need to chase through the surrounding RESHAPE/
            # EXPAND_DIMS ops to read it correctly.
            filt = tensors[int(op["inputs"][1])]
            out_channels, _, kernel_size, _ = [int(d) for d in filt["shape"]]
            out_tensor = tensors[int(op["outputs"][0])]
            new_length = _spatial_length(out_tensor["shape"])
            layers.append({
                "kind": "conv",
                "filters": out_channels,
                "kernel_size": kernel_size,
                "padding": "same" if new_length == current_length else "valid",
                "relu": "Relu" in out_tensor["name"],
            })
            current_length = new_length
            prev_kind = "conv"

        elif name == "MAX_POOL_2D":
            out_tensor = tensors[int(op["outputs"][0])]
            new_length = _spatial_length(out_tensor["shape"])
            pool_size = max(1, round(current_length / new_length))
            layers.append({"kind": "pool", "pool_size": pool_size})
            current_length = new_length
            prev_kind = "pool"

        elif name == "FULLY_CONNECTED":
            if prev_kind in ("conv", "pool"):
                layers.append({"kind": "flatten"})
            weight = tensors[int(op["inputs"][1])]
            units = int(weight["shape"][0])
            out_idx = int(op["outputs"][0])
            layers.append({
                "kind": "dense",
                "units": units,
                "relu": "Relu" in tensors[out_idx]["name"],
            })
            prev_kind = "dense"

        elif name in ("SOFTMAX", "LOGISTIC"):
            # Trailing activation applied to the last dense layer - marks it
            # as this model's classification head.
            for prior in reversed(layers):
                if prior["kind"] == "dense":
                    prior["head_activation"] = "softmax" if name == "SOFTMAX" else "sigmoid"
                    break
            prev_kind = "activation"

        # EXPAND_DIMS / RESHAPE / DELEGATE: pure plumbing, skipped entirely.

    return input_shape, layers


def build_model(name: str, input_shape, layers) -> tf.keras.Model:
    """Rebuilds a (never-trained) Keras model matching `layers`, exactly as
    extracted from the real .tflite file by extract_architecture()."""
    length = _spatial_length(input_shape)
    channels = int(input_shape[-1])
    keras_layers = [tf.keras.layers.Input(shape=(length, channels), name="input")]

    conv_i = pool_i = dense_i = 0
    for spec in layers:
        if spec["kind"] == "conv":
            conv_i += 1
            keras_layers.append(Conv1D(
                spec["filters"], kernel_size=spec["kernel_size"], padding=spec["padding"],
                activation="relu" if spec["relu"] else None, name=f"conv1d_{conv_i}",
            ))
        elif spec["kind"] == "pool":
            pool_i += 1
            keras_layers.append(MaxPooling1D(pool_size=spec["pool_size"], name=f"maxpool_{pool_i}"))
        elif spec["kind"] == "flatten":
            keras_layers.append(Flatten(name="flatten"))
        elif spec["kind"] == "dense":
            head_activation = spec.get("head_activation")
            if head_activation:
                head_cls = HeadSigmoid if head_activation == "sigmoid" else HeadSoftmax
                keras_layers.append(head_cls(spec["units"], activation=head_activation, name=f"head_{head_activation}"))
            else:
                dense_i += 1
                keras_layers.append(Dense(
                    spec["units"], activation="relu" if spec["relu"] else None, name=f"dense_{dense_i}",
                ))

    return tf.keras.Sequential(keras_layers, name=name)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default()

    tflite_paths = sorted(MODELS_DIR.glob("*.tflite"))
    if not tflite_paths:
        raise SystemExit(f"No .tflite models found in {MODELS_DIR}")

    for tflite_path in tflite_paths:
        name = tflite_path.stem
        input_shape, layers = extract_architecture(tflite_path)
        model = build_model(name, input_shape, layers)

        out_path = OUTPUT_DIR / f"{name}_architecture.png"
        rendered = visualkeras.layered_view(
            model,
            legend=True,
            font=font,
            color_map=COLOR_MAP,
            scale_xy=3,
            scale_z=0.6,
            min_xy=25,
            min_z=25,
            max_xy=180,
            max_z=180,
            spacing=35,
            padding=30,
            show_dimension=False,
            one_dim_orientation="z",
            draw_funnel=False,
        )
        canvas = Image.new("RGBA", (rendered.width, rendered.height + TOP_MARGIN_PX), "white")
        canvas.paste(rendered, (0, TOP_MARGIN_PX), rendered if rendered.mode == "RGBA" else None)
        canvas.save(out_path)
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
