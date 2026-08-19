# Provisioning a new Arduino UNO Q from scratch

Step-by-step setup for a fresh Arduino UNO Q running its stock Debian Linux
image, with a shell already reachable (SSH, ADB, or a physical console) as
the board's default user (`arduino`). Every step runs on the board's own
Debian Linux shell regardless of what your own computer runs, except
[step 5](#5-flash-the-mcu-sketch) (runs on your development computer, with
separate Linux/macOS and Windows instructions) and half of
[step 9](#9-set-up-the-gui-as-a-docker-service) (the Docker image build,
which also runs on a dev machine, not the board - see
[`docker/README.md`](../docker/README.md) for why).

Internet access is required to complete this setup - on the board for
installing `uv`, cloning the repository, and resolving Python/Arduino
dependencies, and on the dev machine for the Docker build step above. Every
piece provisioned here runs fully offline afterward - including the GUI's
Docker container, which needs no network access on the board at all.

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

## 6. Wire the WiFi mode jumper (optional)

The GUI's Network Setup card (step 8) is the primary way to switch WiFi
mode - this step is only needed for the advanced/manual fallback path. Wire
a momentary jumper/button between pin **D13** and an adjacent **GND** pin on
the JDIGITAL header - see
[`wifi/README.md`](../wifi/README.md#hardware-wiring-the-jumper).

## 7. Set up the WiFi mode daemon

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
> moment the service restarts - have local/physical access (or the jumper
> from step 6) ready before running this remotely.

Verify:

```bash
systemctl status wifi-mode-switcher.service
```

See [`wifi/README.md`](../wifi/README.md) for the equivalent steps done by
hand (useful if `setup.sh` doesn't fit a given deployment) and the full
daemon behavior (open vs. WPA2-PSK Station networks, retry/fallback,
LED/matrix indicators).

## 8. Run the GUI

For local development/debugging - a provisioned field system instead runs the
GUI as a Docker service, [step 9](#9-set-up-the-gui-as-a-docker-service)
below.

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

## 9. Set up the GUI as a Docker service

Building and installing are two separate steps on two different machines -
see [`docker/README.md`](../docker/README.md) for the full explanation (the
board's storage is usually too tight for a build's transient disk needs, even
though the final image comfortably fits).

On a dev machine (not the board):

```bash
cd docker
./build.sh
```

Fetches every `uv` dependency (the only step here needing internet access)
and produces `docker/riid-gui.tar`. Copy that file, `install.sh`, and
`riid-gui.service` to the board (e.g. into this same `~/Gits/RIID-gui/docker/`
checkout), then on the board:

```bash
cd ~/Gits/RIID-gui/docker
sudo ./install.sh
```

Loads the image and installs/starts it as a systemd service that starts on
boot and runs fully offline from then on - the primary way to deploy a
provisioned field system. Once running, the GUI is reachable at
`http://<board-ip>` on port 80 instead of step 8's `:8080` - stop step 8's
manual `uv run main.py` first if it's still running, since both would
otherwise fight over the DAQ board's serial port.

## 10. Verify the full system

- GUI loads from another device on the network at `http://<board-ip>` (port
  80, via the Docker service from step 9) or `http://<board-ip>:8080` (via
  step 8's manual `uv run main.py`) - shows a "hardware disconnected" banner
  if no DAQ board is attached yet, the rest of the interface still works.
- The LED matrix scrolls status text; LED4 reflects the GUI's current state
  (blue/red/green/purple).
- LED3 shows red (Access Point mode, the default) or white (Station mode).
- The GUI's Network Setup card (Hardware & Calibration tab) switches between
  Access Point and Station mode, and manages known Station networks.
- If the jumper from step 6 is wired, holding it closed for 5+ seconds also
  toggles LED3 and flashes a matching matrix message (`STA MODE - <ssid>`,
  `AP MODE`, or `STA FAILED -> AP MODE`).
