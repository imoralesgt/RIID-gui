"""Renders landscape 3-D "stacked block" architecture diagrams for the two
production RIID models (cnn_multilabel, cnn_deep) into docs/res/.

The layer sequence and every shape/parameter below were verified directly
against the shipped .tflite files (gui/ml_models/*.tflite) via
ai_edge_litert's Interpreter - both models share an identical trunk (same
Conv1D/MaxPooling1D/Dense layer shapes) and only diverge in their final
classification head: cnn_multilabel ends in a 5-way independent LOGISTIC
(sigmoid) layer, cnn_deep in a 9-way mutually-exclusive SOFTMAX layer. This
script rebuilds that verified architecture as a throwaway (never-trained)
Keras model purely so visualkeras has something to draw - no weights from
the real models are used or needed, since only the layer structure matters
for this diagram.

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

import tensorflow as tf
import visualkeras
from PIL import Image, ImageFont

OUTPUT_DIR = Path(__file__).resolve().parents[3] / "docs" / "res"

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
    """Tags cnn_multilabel's final layer with its own type, purely so
    visualkeras can color/legend it separately from the hidden Dense layer."""


class HeadSoftmax(Dense):
    """Tags cnn_deep's final layer with its own type, purely so visualkeras
    can color/legend it separately from the hidden Dense layer."""


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


def build_model(name: str, n_classes: int, head_cls: type) -> tf.keras.Model:
    activation = "sigmoid" if head_cls is HeadSigmoid else "softmax"
    return tf.keras.Sequential([
        tf.keras.layers.Input(shape=(250, 1), name="input"),
        Conv1D(16, kernel_size=15, padding="same", activation="relu", name="conv1d_1"),
        MaxPooling1D(pool_size=2, name="maxpool_1"),
        Conv1D(32, kernel_size=7, padding="same", activation="relu", name="conv1d_2"),
        MaxPooling1D(pool_size=2, name="maxpool_2"),
        Flatten(name="flatten"),
        Dense(32, activation="relu", name="dense_hidden"),
        head_cls(n_classes, activation=activation, name=f"head_{activation}"),
    ], name=name)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default()

    for name, n_classes, head_cls in [
        ("cnn_multilabel", 5, HeadSigmoid),
        ("cnn_deep", 9, HeadSoftmax),
    ]:
        model = build_model(name, n_classes, head_cls)
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
