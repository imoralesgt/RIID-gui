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

**Views (tabs)**

- [`view_spectrum_id`](docs/reference/view_spectrum_id.md) — Spectrum ID tab: live plot, class-probability bars, operator controls.
- [`view_recording`](docs/reference/view_recording.md) — Spectrum Recording tab: sources/shielding directories, batch controls.
- [`view_download`](docs/reference/view_download.md) — Spectra Download tab: bulk file management.
- [`view_calibration`](docs/reference/view_calibration.md) — Hardware & Calibration tab: instrument identity, calibration, DPP settings.
