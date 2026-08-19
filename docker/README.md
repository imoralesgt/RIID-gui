# Running the GUI as a Docker service

Runs `gui/` as an offline Docker container that starts on boot, instead of the
manual `cd gui && uv run main.py` used during development. Building and
installing are two separate steps, run on two **different machines** - do not
run both scripts on the same machine:

| Script | Runs on | Does |
|---|---|---|
| **`docker/build.sh`** | **your dev machine** | Fetches every `uv` dependency and cross-builds a `linux/arm64` image (the Arduino UNO Q's architecture), then saves it to a portable tarball. This is the only step needing internet access or meaningful build-time disk space - the board's own root partition is often too tight for a build's transient peak (builder output + runtime base layers held simultaneously), even when the final image would comfortably fit. |
| **`docker/install.sh`** | **the Arduino UNO Q board** | Loads the tarball `build.sh` already produced and installs/starts it as a systemd service. Needs no network access at all - everything the image needs is already inside the tarball. |

See [Building](#building-run-on-your-dev-machine) and
[Installing on a board](#installing-on-a-board-run-on-the-board) below for the
exact commands for each.

## How it works

- **`Dockerfile`** (repo root, not this directory): a two-stage build. Stage 1
  (`ghcr.io/astral-sh/uv:python3.12-trixie-slim`) runs
  `uv sync --frozen --no-dev --no-editable --all-packages` against the whole
  workspace (`gui`, the `daq-core` submodule's `python-api`,
  `utils/spectrum_recorder`) - this is the only step that touches the
  network. Stage 2 (`python:3.12-slim-trixie`) just copies the resulting
  `/app` (source + `.venv`) over and runs `python main.py` directly, no `uv`
  involved at runtime.
- **The container needs the same three things bare-metal `gui/` needs**:
  - `/var/run/arduino-router.sock` and `/var/run/riid-wifi.sock`, bind-mounted
    straight through - the GUI is only ever a client on these, so this is
    exactly the same pattern already used for the WiFi daemon's own socket
    (see [`../wifi/README.md`](../wifi/README.md)).
  - The DAQ board's USB-serial device, hot-plugged and enumerated dynamically
    (`/dev/ttyUSB*`/`/dev/ttyACM*` via `/dev/serial/by-id/` - see
    `daq-core/NSIL-MCA-DPP4SiPM/sw/python-api/core/daq_hw.py`). The container
    runs `--privileged` with `/dev` bind-mounted rather than pinning a
    specific device node, so it doesn't matter what the DAQ board enumerates
    as.
- **`gui/data` is a named Docker volume (`riid-gui-data`)**, not a bind mount -
  Docker's non-volatile storage primitive, kept independent of the
  container's writable layer (which `docker rm`/a rebuild discards).
  `conf/detectors.json`/`sources.json` loaded with default content in the
  image (such as detector calibration values, MCA configuration, etc.); Docker auto-copies that into the volume the first time it's used. Everything the app writes
  afterward - recordings, downloads, the generated `conf/wifi.json` - persists
  in that volume across restarts, rebuilds, and re-running `install.sh`.
  `gui/logs/` and `gui/gui.log` are plain bind mounts instead.
- **Port 80, not 8080**: the container still listens on 8080 internally
  (`main.py` is unchanged), but `docker run` forwards it to the host's
  default HTTP port 80, so a Dockerized system is reachable at plain
  `http://<board-ip>` (or `http://10.42.0.1` in Access Point mode) - no
  `:8080` suffix. A bare-metal `uv run main.py` deployment is still on 8080 as
  before; which one applies depends on whether this has been set up on that
  particular board. **This board may already run other Docker workloads on
  port 80** (e.g. a different project's GUI container) - `install.sh` checks
  for that every run and refuses to start `riid-gui` rather than fighting
  another running container for the port.

## Layout

- `../Dockerfile`, `../.dockerignore` (repo root - the build context has to be
  the whole workspace, not just `gui/`).
- `build.sh` — builds + saves the image tarball; **run on a dev machine**, see
  [Building](#building-run-on-your-dev-machine) below.
- `install.sh` — loads the tarball and installs the systemd service; **run on
  the board**, see [Installing on a board](#installing-on-a-board-run-on-the-board)
  below.
- `riid-gui.service` — systemd unit template, rendered by `install.sh`.

## Building (run on your dev machine)

**Not the Arduino Uno Q board.** Needs Docker with `buildx` support for cross-building to
`linux/arm64` - already the default with Docker Desktop:

```bash
# On your dev machine:
cd docker
./build.sh
```

Produces `docker/riid-gui.tar` (a few hundred MB - compressed, so notably
smaller than the image's unpacked size). No `sudo` needed here; this doesn't
touch the dev machine's systemd/Docker service config at all. Next: copy that
tarball to the board and continue with
[Installing on a board](#installing-on-a-board-run-on-the-board) below.

## Installing on a board (run on the board)

**Not your dev machine.** Copy the tarball, `install.sh`, and
`riid-gui.service` to the board first (e.g. into its `~/Gits/RIID-gui/docker/`
checkout):

```bash
# From your dev machine, to the board:
scp riid-gui.tar install.sh riid-gui.service arduino@<board>:~/Gits/RIID-gui/docker/
```

Then, on the board itself:

```bash
# On the board:
cd ~/Gits/RIID-gui/docker
sudo ./install.sh
```

Installs Docker if not already present, checks that nothing else is already
using host port 80 (refuses to proceed rather than fight another running
container for it - see [How it works](#how-it-works) above), loads the
tarball, installs the `riid-gui.service` unit with paths pointed at this
checkout, and starts it. Re-running it (after copying a freshly rebuilt
tarball over) is safe: loads the new image and restarts the service with it -
the `riid-gui-data` volume is untouched either way.

> **If the board's root partition is still too small for the loaded image**
> (e.g. the UNO Q's factory layout splits a small root partition from a much
> larger, separate `/home/<user>` one) - relocating Docker's entire data-root
> (`/var/lib/docker`) to that larger partition is the standard fix, but do it
> **manually and deliberately**, not as part of this script: it requires
> briefly stopping the Docker daemon, which stops *every* container on the
> board, not just `riid-gui` - check `docker ps` first for anything else
> running that this would affect.
> ```bash
> sudo systemctl stop docker
> sudo mkdir -p /home/<user>/docker-data
> sudo cp -a /var/lib/docker/. /home/<user>/docker-data/
> # add {"data-root": "/home/<user>/docker-data"} to /etc/docker/daemon.json
> sudo systemctl start docker
> docker info --format '{{.DockerRootDir}}'  # confirm it moved
> ```

## Inspecting / backing up persistent data

```bash
docker volume inspect riid-gui-data
```

Its `Mountpoint` is a regular host directory (owned by Docker, under
`/var/lib/docker/volumes/`) - readable/copyable like any other for a backup,
though `gui/data/conf/wifi.json` and any live spectra are best read through
the GUI itself rather than while the container is writing to them.

## Rebuilding after a code change

Same two machines, same order as initial setup:

1. **On your dev machine:** `./build.sh`.
2. Copy the new `riid-gui.tar` to the board.
3. **On the board:** `sudo docker/install.sh` (or just `docker load -i
   riid-gui.tar` + `systemctl restart riid-gui.service`, without touching the
   systemd unit again).
