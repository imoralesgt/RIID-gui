# RIID visualization interface (Arduino UNO Q)

The MCU-side companion to the GUI: a sketch that runs on the **microcontroller (MCU)** core of the Arduino UNO Q board embedded in the RIID system, driving the board's onboard RGB LED and the 12x8 LED matrix as a physical status display for the RIID survey in progress. It performs no acquisition or inference of its own — it only renders state the GUI pushes to it.

## How it works

The UNO Q has two processors on one board: a Linux-capable MPU (where `gui/` runs) and a Zephyr-based MCU (where this sketch runs). The two communicate over [`Arduino_RouterBridge`](https://github.com/arduino-libraries/Arduino_RouterBridge), an RPC channel exposed on the MPU side as a Unix socket (`/var/run/arduino-router.sock`). `gui/mcu_interface.py`'s `ArduinoInterface` connects to that socket and calls into the sketch below by name; the sketch registers its handlers with `Bridge.provide(...)` in [`riid_viz.ino`](app/riid_viz/riid_viz.ino).

| RPC method | Called from | Effect |
|---|---|---|
| `update_status_led(status: int)` | `ArduinoInterface.update_status` | Sets the RGB LED to match the RIID system's current state: `0`=`IDLE` (blue), `1`=`BG_RECORDING` (red), `2`=`RIID_SURVEY` (green), `3`=`BATCH_RECORDING` (purple = red + blue) |
| `update_text_matrix(text: str)` | `ArduinoInterface.update_text` | Replaces the scrolling message on the LED matrix (GUI-side sanitized to `A-Z 0-9` and a small set of punctuation before sending) |
| `set_scroll_speed(speed: int)` | `ArduinoInterface.update_scroll_speed` | Sets the delay (ms) between scroll steps on the matrix |

The status index/color mapping mirrors `gui/mcu_interface.py`'s own `ArduinoInterface.STATUS` dict one-for-one — if either side's mapping ever changes, the other must be updated to match. On the GUI side, `RIIDCoreService.set_state()` (`gui/riid_service.py`) is the single place that pushes both the LED color and the matrix's state text together, exactly once per state transition; see [`gui/README.md`](../gui/README.md#mcu-integration-arduino-uno-q) for how the rest of the integration (live RIID detection text during a survey, etc.) is wired up on the GUI side.

Three more RPC methods drive the WiFi AP/Station mode indicator — a second, physically distinct RGB LED ("LED3") and an optional jumper cable (D13/PB13, wired to GND; see [`wifi/README.md`](../wifi/README.md) for wiring) as an advanced/manual fallback to the GUI's own Network Setup card. Unlike the three above, these are **not** called by the GUI at all: they're consumed by the standalone [`wifi/wifi_mode_daemon.py`](../wifi/README.md), which connects to the same RPC socket independently so that WiFi/NetworkManager switching stays out of the (future-containerized) GUI process. The GUI instead talks to that daemon over a separate local socket - see `wifi/README.md` for that protocol.

| RPC method | Called from | Effect |
|---|---|---|
| `poll_wifi_button()` | `wifi/wifi_mode_daemon.py` | Read-clears request/response call: returns whether the WiFi-mode jumper was held for 5s+ since the last poll. The MCU does all the hold-duration surveying itself; the caller just reacts to a `true` result. |
| `update_wifi_led(mode: int)` | `wifi/wifi_mode_daemon.py` | Sets LED3 to match the current WiFi mode: `0`=Access Point (red), `1`=Station (white) |
| `show_transient_text(text: str, duration_ms: int)` | `wifi/wifi_mode_daemon.py` | Flashes `text` on the LED matrix for `duration_ms`, then automatically reverts to whatever text was showing beforehand (e.g. the current RIID status) — lets the WiFi daemon show a one-shot `AP MODE`/`STA MODE` message without needing to know or restore the GUI's own status text |

This is a separate, active component from the early Arduino Uno Q **inference** target under `ml-core/` (`inference.py`/`mcu.cpp`) — that one ran RIID classification on-device over serial and has been superseded by the GUI's own `ml_inference.py` pipeline, and is no longer used in production (see the root [README](../README.md#machine-learning-model-riid)). This sketch only renders status/text; it does no classification.

## Layout

- `app/riid_viz/riid_viz.ino` — the sketch (LED matrix scrolling text + RGB status LED, RPC handlers).
- `app/riid_viz/sketch.yaml` — `arduino-cli` build profile (FQBN `arduino:zephyr:unoq`, port, pinned library versions).
- `scripts/upload.sh [sketch-dir]` — compiles and uploads to a single board: direct USB/serial if the board is found on a serial port, otherwise falls back to an SSH/network upload (needs `UNOQ_HOST`, and usually `UNOQ_PASSWORD`, from `.env`).
- `scripts/upload_fleet.sh [sketch-dir]` — compiles once and uploads the same build to every board listed in `boards.txt`, over SSH, for provisioning multiple RIID systems at once.
- `scripts/build_prebuilt.sh [sketch-dir]` — compiles and copies the result into `prebuilt/`, for anyone who wants to flash without installing this sketch's libraries or the `arduino:zephyr` core's full toolchain locally.
- `scripts/upload_prebuilt.sh [binary-file]` — uploads an already-built binary (defaults to the tracked `prebuilt/riid_viz.elf-zsk.bin`) over SSH/network, without compiling.
- `prebuilt/riid_viz.elf-zsk.bin` — tracked, ready-to-flash build of the current sketch; see [Using a pre-built binary](#using-a-pre-built-binary) below.
- `scripts/_common.sh` — shared helpers (env loading, artifact/tool path resolution) sourced by the upload scripts.
- `boards.txt` / `boards.txt.example` — one remote board hostname per line, for `upload_fleet.sh`. Gitignored; copy the example to get started.
- `.env` / `.env.example` — `UNOQ_HOST` / `UNOQ_PASSWORD` for the SSH/network upload path. Gitignored; copy the example to get started.
- `.vscode/tasks.json` — VS Code build/upload tasks ("Compile Arduino MCU Sketch", "Fast deploy and run") wired to run from `app/riid_viz`.

## Installing the Arduino core & libraries

Requires [`arduino-cli`](https://arduino.github.io/arduino-cli/). `_common.sh`'s `resolve_flash_artifacts` invokes `arduino-cli compile --fqbn arduino:zephyr:unoq` directly (not `--profile`), so it builds against whatever core/libraries are installed globally in your `arduino-cli` environment (`~/.arduino15`), not an isolated per-profile environment — `app/riid_viz/sketch.yaml` documents the exact versions to install, but doesn't install them for you.

Install the `arduino:zephyr` core (provides the UNO Q's FQBN, `arduino:zephyr:unoq`) and the libraries listed in `sketch.yaml`. Update both indexes before installing the core - `core install` pulls in `Arduino_RouterBridge` and the rest as bundled library dependencies, which fails with a "Library not found" error if the library index hasn't been fetched yet:

```bash
arduino-cli core update-index
arduino-cli lib update-index
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

### Windows-specific setup

Verified working via [Git for Windows](https://git-scm.com/download/win)'s
bundled `bash.exe`, without WSL. Run all commands below, and the
`upload.sh` command in the next section, from a Git Bash shell - these are
bash scripts and won't run under PowerShell or `cmd.exe`.

`arduino-cli` isn't available through `winget`. Install it with the
official install script, which also runs fine under Git Bash:

```bash
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh -o /tmp/arduino_install.sh
sh /tmp/arduino_install.sh
```

This installs to `~/.local/bin`, which Git Bash already puts on `PATH`.

`upload.sh` also shells out to `python3` to parse `arduino-cli board list`'s
JSON output. Windows has no real Python installed by default - `python3`
and `python` on a stock `PATH` resolve to non-functional Microsoft Store
alias stubs. Install a real Python (e.g. `winget install Python.Python.3.12`),
then add a `python3` shim, since the python.org installer only creates a
`python.exe`, not `python3.exe`:

```bash
mkdir -p ~/.local/bin
printf '#!/bin/bash\nexec python "$@"\n' > ~/.local/bin/python3
chmod +x ~/.local/bin/python3
```

## Building & uploading

Run these from your development computer, with the board connected over
USB - not on the UNO Q's own Linux side. Its installed `arduino:zephyr`
core version can differ from the one installed above, producing a build
that compiles without errors but isn't equivalent to the tested one.

`upload.sh` has been verified on both Linux and Windows (Git Bash, no WSL
- see [Windows-specific setup](#windows-specific-setup) above), both over
direct USB and over its SSH/network fallback. `upload_fleet.sh` has also
been verified on Windows. `upload_prebuilt.sh` shares the same underlying
`resolve_flash_artifacts`/`remoteocd` mechanism already verified through
the scripts above on both OSes, but hasn't been run directly on either
one. Neither script has been tried on macOS - they're plain bash and
should work the same way
there, but that's expected, untested territory, not a
regression, if you hit something platform-specific.

Single board, from anywhere in the repo (or pass a sketch directory as `$1`):

```bash
scripts/upload.sh
```

Fleet upload to every host in `boards.txt` (copy `boards.txt.example` and `.env.example` first):

```bash
scripts/upload_fleet.sh
```

Both scripts default to compiling `app/riid_viz` when no sketch directory is given, so they can be run from anywhere in the repo.

## Using a pre-built binary

`prebuilt/riid_viz.elf-zsk.bin` is a tracked, ready-to-flash build of the
current sketch, for flashing a board without installing this sketch's
libraries or the full `arduino:zephyr` core toolchain - only `arduino-cli`
and the core itself (for its board/tool definitions) are needed, not the
library set from [Installing the Arduino core & libraries](#installing-the-arduino-core--libraries)
above.

```bash
scripts/upload_prebuilt.sh
```

This always uploads over SSH/network (needs `UNOQ_HOST`, and usually
`UNOQ_PASSWORD`, from `.env` - same as `upload_fleet.sh`); there isn't
currently a reliable direct-USB path for uploading a pre-built binary
without compiling, so use `scripts/upload.sh` instead if the board is only
reachable over USB.

After changing the sketch, regenerate the tracked binary and commit it:

```bash
scripts/build_prebuilt.sh
```
