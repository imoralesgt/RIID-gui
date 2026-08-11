# RIID visualization interface (Arduino UNO Q)

The MCU-side companion to the GUI: a sketch that runs on the **microcontroller (MCU)** core of the Arduino UNO Q board embedded in the RIID system, driving the board's onboard RGB LED and the 12x8 LED matrix as a physical status display for the RIID survey in progress. It performs no acquisition or inference of its own — it only renders state the GUI pushes to it.

## How it works

The UNO Q has two processors on one board: a Linux-capable MPU (where `gui/` runs) and a Zephyr-based MCU (where this sketch runs). The two communicate over [`Arduino_RouterBridge`](https://github.com/arduino-libraries/Arduino_RouterBridge), an RPC channel exposed on the MPU side as a Unix socket (`/var/run/arduino-router.sock`). `gui/mcu_interface.py`'s `ArduinoInterface` connects to that socket and calls into the sketch below by name; the sketch registers its handlers with `Bridge.provide(...)` in [`riid_viz.ino`](app/riid_viz/riid_viz.ino).

| RPC method | Called from | Effect |
|---|---|---|
| `update_status_led(status: int)` | `ArduinoInterface.update_status` | Sets the RGB LED: `0`=idle (blue), `1`=recording background (red), `2`=surveying, no result yet (green), `3`=surveying, result found (aqua) |
| `update_text_matrix(text: str)` | `ArduinoInterface.update_text` | Replaces the scrolling message on the LED matrix (GUI-side sanitized to `A-Z 0-9` and a small set of punctuation before sending) |
| `set_scroll_speed(speed: int)` | `ArduinoInterface.update_scroll_speed` | Sets the delay (ms) between scroll steps on the matrix |

This is a separate, active component from the early Arduino Uno Q **inference** target under `deprecated-ml-core/` (`inference.py`/`mcu.cpp`) — that one ran RIID classification on-device over serial and has been superseded by the GUI's own `ml_inference.py` pipeline. This sketch only renders status/text; it does no classification.

## Layout

- `app/riid_viz/riid_viz.ino` — the sketch (LED matrix scrolling text + RGB status LED, RPC handlers).
- `app/riid_viz/sketch.yaml` — `arduino-cli` build profile (FQBN `arduino:zephyr:unoq`, port, pinned library versions).
- `scripts/upload.sh [sketch-dir]` — compiles and uploads to a single board: direct USB/serial if the board is found on a serial port, otherwise falls back to an SSH/network upload (needs `UNOQ_HOST`, and usually `UNOQ_PASSWORD`, from `.env`).
- `scripts/upload_fleet.sh [sketch-dir]` — compiles once and uploads the same build to every board listed in `boards.txt`, over SSH, for provisioning multiple RIID systems at once.
- `scripts/_common.sh` — shared helpers (env loading, artifact/tool path resolution) sourced by both upload scripts.
- `boards.txt` / `boards.txt.example` — one remote board hostname per line, for `upload_fleet.sh`. Gitignored; copy the example to get started.
- `.env` / `.env.example` — `UNOQ_HOST` / `UNOQ_PASSWORD` for the SSH/network upload path. Gitignored; copy the example to get started.
- `.vscode/tasks.json` — VS Code build/upload tasks ("Compile Arduino MCU Sketch", "Fast deploy and run") wired to run from `app/riid_viz`.

## Installing the Arduino core & libraries

Requires [`arduino-cli`](https://arduino.github.io/arduino-cli/). `_common.sh`'s `resolve_flash_artifacts` invokes `arduino-cli compile --fqbn arduino:zephyr:unoq` directly (not `--profile`), so it builds against whatever core/libraries are installed globally in your `arduino-cli` environment (`~/.arduino15`), not an isolated per-profile environment — `app/riid_viz/sketch.yaml` documents the exact versions to install, but doesn't install them for you.

Install the `arduino:zephyr` core (provides the UNO Q's FQBN, `arduino:zephyr:unoq`) and the libraries listed in `sketch.yaml`:

```bash
arduino-cli core update-index
arduino-cli core install arduino:zephyr

arduino-cli lib install \
  "ArduinoGraphics@1.1.5" \
  "Arduino_RouterBridge@0.4.3" \
  "Arduino_RPClite@0.3.0" \
  "MsgPack@0.4.2" \
  "DebugLog@0.8.4" \
  "ArxTypeTraits@0.3.2" \
  "ArxContainer@0.7.0"
```

Verify with `arduino-cli core list` / `arduino-cli lib list`. If `sketch.yaml` is ever bumped to newer library versions, re-run the `lib install` command with the updated version pins to keep your environment in sync.

## Building & uploading

Single board, from within `app/riid_viz` (or pass a sketch directory as `$1`):

```bash
../../scripts/upload.sh .
```

Fleet upload to every host in `boards.txt` (copy `boards.txt.example` and `.env.example` first):

```bash
scripts/upload_fleet.sh
```

Both scripts default to compiling `app/riid_viz` when no sketch directory is given, so they can be run from anywhere in the repo.
