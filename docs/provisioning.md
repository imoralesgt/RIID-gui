# Provisioning a new Arduino UNO Q from scratch

Step-by-step setup for a fresh Arduino UNO Q running its stock Debian Linux
image, with a shell already reachable (SSH, ADB, or a physical console) as
the board's default user (`arduino`). Every step runs on the board's own
Debian Linux shell regardless of what your own computer runs, except
[step 4](#4-flash-the-mcu-sketch), which runs on your development computer,
with separate Linux/macOS and Windows instructions.

To get a brand new board to that point - flashing the stock image and
reaching a shell over SSH or ADB - follow steps 1-8 of
[Mjrovai's Arduino UNO Q setup guide](https://github.com/Mjrovai/ARDUINO-UNO-Q/blob/main/Setup/README.md)
first.

Internet access on the board is required to complete this setup - installing
`uv`, cloning the repository, and downloading the published GUI Docker image
in [step 5](#5-install-the-gui-and-wifi-daemon) all reach out to the
network. Every piece provisioned here runs offline afterward - including the
GUI's Docker container, which needs no network access to run.

## 1. Prerequisites

Confirm the shell user is in the `dialout` group (needed for serial device
access - `/dev/ttyACM*`, `/dev/ttyHS*`):

```bash
groups
```

If `dialout` isn't listed:

```bash
sudo usermod -aG dialout $USER
```

Log out and back in (or `newgrp dialout`) for the group change to take
effect.

Confirm `arduino-cli` and the `arduino:zephyr` core are installed (both
ship with the stock UNO Q image):

```bash
arduino-cli version
arduino-cli core list
```

If the `arduino:zephyr` core or its libraries are missing, install them —
see [`mcu/README.md`](../mcu/README.md#installing-the-arduino-core--libraries).

## 2. Install `uv`

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Installs to `~/.local/bin/uv` and wires it onto `PATH` via
`~/.bashrc`/`~/.profile`. Start a new shell (or `source ~/.bashrc`)
afterward so `uv` is directly runnable.

## 3. Clone the repository

```bash
mkdir -p ~/Gits
cd ~/Gits
git clone --recursive git@github.com:imoralesgt/RIID-gui.git
cd RIID-gui
```

`--recursive` pulls in the DAQ communications submodule
(`daq-core/NSIL-MCA-DPP4SiPM`). If already cloned without it:

```bash
git submodule update --init --recursive
```

The rest of this guide assumes the repository lives at `~/Gits/RIID-gui` -
substitute the actual path in the systemd unit step below if different.

## 4. Flash the MCU sketch

> **Run this step on your development computer, not on the UNO Q itself.**
> Compiling on the UNO Q's Linux side is not supported: its installed
> core version can differ from what's tested here, producing a build that
> compiles without errors but isn't equivalent to the one this guide
> verifies against.

### Linux / macOS

Assumes `arduino-cli` and the `arduino:zephyr` core are already installed
on your computer - see
[`mcu/README.md`](../mcu/README.md#installing-the-arduino-core--libraries)
if not, with the board connected over USB:

```bash
cd mcu
./scripts/upload.sh app/riid_viz
```

### Windows

Verified via [Git for Windows](https://git-scm.com/download/win)'s bundled
`bash.exe`, without WSL - run every command below from a Git Bash shell,
not PowerShell or `cmd.exe`. `upload.sh` calls `python3`, but the Windows
Python installer only creates a `python.exe`, not `python3.exe` - install
`arduino-cli`, the `arduino:zephyr` core, and a small `python3` wrapper
script that just calls `python.exe` first - see
[`mcu/README.md`](../mcu/README.md#windows-specific-setup) - then, with the
board connected over USB:

```bash
cd mcu
./scripts/upload.sh app/riid_viz
```

### After flashing

Drives LED4, LED3, and the LED matrix. See [`mcu/README.md`](../mcu/README.md)
for the firmware/RPC details.

For batch-provisioning multiple RIID systems, `scripts/upload_fleet.sh`
compiles the sketch once and uploads it over SSH to every host listed in
`boards.txt` (copy `boards.txt.example` and `.env.example` first) - see
[`mcu/README.md`](../mcu/README.md#layout) for setup. This has only been
verified on Linux so far; it should work the same way under Windows Git
Bash or on macOS, but neither has actually been tried.

## 5. Install the GUI and WiFi daemon

Installs the GUI as a Docker service and, optionally, the WiFi mode daemon,
in one pass. `--with-wifi`/`--skip-wifi` skip the interactive WiFi prompt,
for scripted use. It downloads the GUI image from Releases first, while the
board's existing network connection is still up, and only then sets up the
WiFi daemon - restarting it applies Access Point mode immediately, which can
drop that connection if WiFi is this board's only network path. If
`docker/riid-gui.tar` is already there - built locally with
[`docker/build.sh`](../docker/build.sh) and copied over, or downloaded from
[Releases](https://github.com/imoralesgt/RIID-gui/releases) by hand - it
uses that instead of downloading it again.

```bash
cd ~/Gits/RIID-gui
sudo ./install.sh
```

Both pieces start on boot and need no network access afterward. The GUI is
then reachable at `http://<board-ip>` on port 80. See
[`docker/README.md`](../docker/README.md) and
[`wifi/README.md`](../wifi/README.md) for what each piece does, and
[Advanced: manual / individual setup](#advanced-manual--individual-setup)
below to install either one by hand instead, or to run the GUI directly with
`uv` for local development.

This doesn't flash the MCU sketch ([step 4](#4-flash-the-mcu-sketch)) - that
step runs on a separate development computer, not the board, so it stays
manual; the GUI and WiFi daemon both work without it, but the LED4/LED3/LED
matrix physical status display and the manual jumper-wire AP/STA toggle (see
[WiFi mode jumper](#wifi-mode-jumper-hardware-fallback) at the end of this
guide) need it.

## 6. Verify the full system

- GUI loads from another device on the network at `http://<board-ip>` (port
  80) - shows a "hardware disconnected" banner if no DAQ board is attached
  yet, the rest of the interface still works.
- The LED matrix scrolls status text; LED4 reflects the GUI's current state
  (blue/red/green/purple).
- LED3 shows red (Access Point mode, the default) or white (Station mode).
- The GUI's Network Setup card (Hardware & Calibration tab) switches between
  Access Point and Station mode, and manages known Station networks.
- If the [WiFi mode jumper](#wifi-mode-jumper-hardware-fallback) is wired,
  holding it closed for 5+ seconds also toggles LED3 and flashes a matching
  matrix message (`STA MODE - <ssid>`, `AP MODE`, or `STA FAILED -> AP
  MODE`).

## Advanced: manual / individual setup

`install.sh` (step 5) is the standard way to provision a field system. Use
the steps below instead for a non-Arduino Linux machine (skip the WiFi
daemon entirely - see [`wifi/README.md`](../wifi/README.md)), for iterating
on GUI code without rebuilding the Docker image, or to set up just one piece
of the system by hand.

### Run the GUI directly with `uv`

Skips the Docker image - runs the GUI straight from source, for local
development/debugging.

```bash
cd ~/Gits/RIID-gui
uv sync
```

Sets up the shared `uv` workspace venv (`gui`, `utils/spectrum_recorder`,
and the DAQ `python-api` submodule).

```bash
cd ~/Gits/RIID-gui/gui
uv run main.py
```

The GUI listens on all network interfaces, port 8080 - not just
`localhost`. The board typically has no monitor/keyboard/mouse attached in
the field, so access it from a browser on another device on the same
network (lab computer, laptop, tablet) instead. Find the board's IP
address:

```bash
hostname -I
```

Then open `http://<board-ip>:8080` (or `http://<tailscale-hostname>:8080`
if reachable over Tailscale) from that other device. Stop this before
running the Docker service from [step 5](#5-install-the-gui-and-wifi-daemon)
if both would otherwise fight over the DAQ board's serial port.

### Set up the WiFi mode daemon by hand

```bash
cd ~/Gits/RIID-gui/wifi
sudo ./setup.sh
```

Prompts for the Access Point SSID/passphrase, then the Station network
SSID/passphrase (defaults to the shared `RIID_IAEA` for the AP passphrase),
then writes `config/wifi_config.json`, runs `uv sync`, installs the sudoers
rule and systemd service (both automatically pointed at this checkout), and
starts the daemon.

> **Note:** this restarts the daemon, which immediately applies the boot
> mode in `config/wifi_config.json` (Access Point, on a fresh setup). If
> this board's only network path is the WiFi interface being reconfigured,
> an SSH/Tailscale session over that same network will be dropped the
> moment the service restarts - have local/physical access (or the
> [WiFi mode jumper](#wifi-mode-jumper-hardware-fallback)) ready before
> running this remotely.

Verify:

```bash
systemctl status wifi-mode-switcher.service
```

See [`wifi/README.md`](../wifi/README.md) for the full daemon behavior (open
vs. WPA2-PSK Station networks, retry/fallback, LED/matrix indicators).

### Set up the GUI Docker service by hand

The board isn't meant to build this image itself - see
[`docker/README.md`](../docker/README.md) for the full explanation (its
storage is usually too tight for a build's transient disk needs, even though
the final image comfortably fits). Download the latest published build from
the repository's [Releases](https://github.com/imoralesgt/RIID-gui/releases)
instead:

```bash
cd ~/Gits/RIID-gui/docker
curl -LO https://github.com/imoralesgt/RIID-gui/releases/latest/download/riid-gui.tar
sudo ./install.sh
```

If that download doesn't work, build the image on a dev machine instead with
[`docker/build.sh`](../docker/build.sh) and copy the resulting `riid-gui.tar`
here before running `install.sh` - see
[`docker/README.md`](../docker/README.md#building-run-on-your-dev-machine).

Loads the image and installs/starts it as a systemd service that starts on
boot and runs offline from then on. Once running, the GUI is reachable at
`http://<board-ip>` on port 80 instead of the `uv run main.py` path's
`:8080` above - stop that first if it's still running, since both would
otherwise fight over the DAQ board's serial port.

## WiFi mode jumper (hardware fallback)

The WiFi daemon also supports switching between Access Point and Station
mode from a wired jumper instead of the GUI's Network Setup card - wire a
momentary jumper/button between pin **D13** and an adjacent **GND** pin on
the JDIGITAL header, see
[`wifi/README.md`](../wifi/README.md#hardware-wiring-the-jumper) for wiring
details. This exists as a fallback for when the GUI isn't reachable; it
isn't part of normal provisioning, and most deployments never wire it.
