# gui

The NiceGUI web application for the RIID station. See the [repository README](../README.md) for installation, usage, and a tour of the GUI's features (with screenshots).

## API reference

Module/class/function reference, generated automatically from the docstrings in `gui/*.py` via [lazydocs](https://github.com/ml-tooling/lazydocs), and kept in sync with `main` by the `gui-docs.yml` GitHub Actions workflow.

**Application entry point**

- [`main`](docs/reference/main.md) — top-level NiceGUI app shell and page route.
- [`config`](docs/reference/config.md) — app-wide constants, filesystem layout, logging, brand palette.

**Backend**

- [`riid_service`](docs/reference/riid_service.md) — DAQ hardware handle, acquisition loops, ML pipeline invocation, spectrum file I/O.
- [`state_engine`](docs/reference/state_engine.md) — hardware/source JSON database persistence and device discovery.
- [`ml_inference`](docs/reference/ml_inference.md) — on-device RIID classification: model loading, inference, thresholds.
- [`ml_preprocessing`](docs/reference/ml_preprocessing.md) — background subtraction and log10/smoothing/decimation feature pipeline.
- [`mcu_interface`](docs/reference/mcu_interface.md) — RPC client to the Arduino UNO Q's MCU sketch (RGB status LED + LED matrix text).

**Views (tabs)**

- [`view_spectrum_id`](docs/reference/view_spectrum_id.md) — Spectrum ID tab: live plot, class-probability bars, operator controls.
- [`view_recording`](docs/reference/view_recording.md) — Spectrum Recording tab: sources/shielding directories, batch controls.
- [`view_download`](docs/reference/view_download.md) — Spectra Download tab: bulk file management.
- [`view_calibration`](docs/reference/view_calibration.md) — Hardware & Calibration tab: instrument identity, calibration, DPP settings.

## MCU integration (Arduino UNO Q)

The GUI drives the Arduino UNO Q's onboard RGB LED and 12x8 LED matrix as a physical status display for the RIID station. `mcu_interface.py`'s `ArduinoInterface` is a thin RPC client, over the [`Arduino_RouterBridge`](https://github.com/arduino-libraries/Arduino_RouterBridge) Unix socket (`/var/run/arduino-router.sock`), to the sketch running on the board's own MCU core — see [`mcu/README.md`](../mcu/README.md) for the firmware side and its RPC method table. A missing/unreachable bridge (no board attached, or running off-board) is handled gracefully: `ArduinoInterface.get_status()` reports whether the connection is actually up, and every call site checks it before pushing an update, so the rest of the GUI works normally without the board.

`RIIDCoreService` (`riid_service.py`) is the only code that talks to `mcu_iface` — the view layer never calls it directly, matching the rest of this codebase's hardware-belongs-to-the-service-layer pattern:

- `set_state()` pushes both the RGB LED color and the LED matrix's status text exactly once, on every state transition (`IDLE` / `BG_RECORDING` / `RIID_SURVEY` / `BATCH_RECORDING`) — matching the sketch's own color mapping (blue / red / green / purple, documented in `mcu/README.md`).
- `_execute_ml_pipeline()` additionally re-drives the LED matrix text with the detected isotope(s) (or `"Background"`), but only while a survey is actually running (`state == 'RIID_SURVEY'`) — since that method is only ever called from inside the survey loop, it naturally stops firing the instant the survey stops, so it can never race with or overwrite `set_state()`'s own status text.