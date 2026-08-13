# Provisioning a new Arduino UNO Q from scratch

Step-by-step setup for a fresh Arduino UNO Q running its stock Debian Linux
image, with a shell already reachable (SSH, ADB, or a physical console) as
the board's default user (`arduino`). Every step runs on the board's own
Debian Linux shell regardless of what your own computer runs, except
[step 5](#5-flash-the-mcu-sketch), which runs on your development computer
and has separate Linux/macOS and Windows instructions.

Internet access on the board is required to complete this setup (installing
`uv`, cloning the repository, and resolving Python/Arduino dependencies all
reach out to the network). A future release will provide a fully offline
Docker image, removing this requirement entirely.

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

## 4. Install the GUI's Python dependencies

```bash
cd ~/Gits/RIID-gui
uv sync
```

Sets up the shared `uv` workspace venv (`gui`, `utils/spectrum_recorder`,
and the DAQ `python-api` submodule).

## 5. Flash the MCU sketch

> **Run this step on your development computer, not on the UNO Q itself.**
> Compiling on the UNO Q's own Linux side is not supported: its installed
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
not PowerShell or `cmd.exe`. Install `arduino-cli`, the `arduino:zephyr`
core, and the `python3` shim `upload.sh` depends on first - see
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

## 6. Wire the external WiFi mode button

Wire a momentary push-button between pin **D13** and an adjacent **GND**
pin on the JDIGITAL header - see
[`wifi/README.md`](../wifi/README.md#hardware-wiring-the-button).

## 7. Set up the WiFi mode daemon

```bash
cd ~/Gits/RIID-gui/wifi
sudo ./setup.sh
```

Prompts for the system ID, the Station network SSID/passphrase, and the
Access Point passphrase (defaults to the shared `RIID_IAEA`), then writes
`config/wifi_config.json`, runs `uv sync`, installs the sudoers rule and
systemd service (both automatically pointed at this checkout), and starts
the daemon.

Verify:

```bash
systemctl status wifi-mode-switcher.service
```

See [`wifi/README.md`](../wifi/README.md) for the equivalent steps done by
hand (useful if `setup.sh` doesn't fit a given deployment) and the full
daemon behavior (open vs. WPA2-PSK Station networks, retry/fallback,
LED/matrix indicators).

## 8. Run the GUI

```bash
cd ~/Gits/RIID-gui/gui
uv run main.py
```

The GUI listens on all network interfaces, port 8080 - not just
`localhost`. The board itself typically has no monitor/keyboard/mouse
attached in the field, so access it from a browser on another device on
the same network (lab computer, laptop, tablet) instead. Find the board's
IP address:

```bash
hostname -I
```

Then open `http://<board-ip>:8080` (or `http://<tailscale-hostname>:8080`
if reachable over Tailscale) from that other device.

## 9. Verify the full system

- GUI loads at `http://<board-ip>:8080` from another device on the network
  (shows a "hardware disconnected" banner if no DAQ board is attached yet -
  the rest of the interface still works).
- The LED matrix scrolls status text; LED4 reflects the GUI's current state
  (blue/red/green/purple).
- LED3 shows white (Station mode, the default) or red (AP mode).
- Holding the WiFi button for 5+ seconds toggles LED3 and flashes a
  matching matrix message (`STA MODE - <ssid>`, `AP MODE`, or
  `STA FAILED -> AP MODE`).
