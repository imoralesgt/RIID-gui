# Provisioning a new Arduino UNO Q from scratch

Step-by-step setup for a fresh Arduino UNO Q running its stock Debian Linux
image, with a shell already reachable (SSH, ADB, or a physical console) as
the board's default user (`arduino`).

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

```bash
cd mcu
./scripts/upload.sh app/riid_viz
```

Drives LED4, LED3, and the LED matrix. See [`mcu/README.md`](../mcu/README.md)
for the firmware/RPC details.

For batch-provisioning multiple RIID systems, `scripts/upload_fleet.sh`
compiles the sketch once and uploads it over SSH to every host listed in
`boards.txt` (copy `boards.txt.example` and `.env.example` first) - see
[`mcu/README.md`](../mcu/README.md#layout) for setup.

## 6. Wire the external WiFi mode button

Wire a momentary push-button between pin **D13** and an adjacent **GND**
pin on the JDIGITAL header - see
[`wifi/README.md`](../wifi/README.md#hardware-wiring-the-button).

## 7. Set up the WiFi mode daemon

```bash
cd ~/Gits/RIID-gui/wifi
uv sync

cp config/wifi_config.json.example config/wifi_config.json
```

Edit `config/wifi_config.json` and set:

- `sys_id` — this system's identifier (e.g. `"SYS06"`), used to build the
  Access Point SSID (`IAEA_RIID_SYS06`).
- `sta_ssid` — the SSID of the network this system should connect to in station mode (e.g. `"SEIB-GUEST"`).
- `sta_psk` — the network's WPA2 passphrase (in Station mode), or `""` (empty string) if the network is open/passwordless.

Leave `ap_psk` and `max_sta_retries` at their defaults (`"RIID_IAEA"` and
`3`) unless this deployment specifically needs different values.

Scope passwordless `sudo` to the switch script:

```bash
sudo visudo -f /etc/sudoers.d/riid-wifi
```

Add this line, replacing `arduino` with the actual username if different,
and the path with wherever the repository was cloned in step 3 if not
`~/Gits/RIID-gui`:

```
arduino ALL=(root) NOPASSWD: /home/arduino/Gits/RIID-gui/wifi/scripts/switch_wifi_mode.sh
```

If the repository was cloned somewhere other than `~/Gits/RIID-gui`, or if
`uv` was installed under a different user's home directory, open
`systemd/wifi-mode-switcher.service` and update its `WorkingDirectory` and
`ExecStart` lines accordingly, for example:

```
WorkingDirectory=/home/arduino/Gits/RIID-gui/wifi
ExecStart=/home/arduino/.local/bin/uv run --offline wifi_mode_daemon.py
```

Install and start the systemd service:

```bash
sudo cp systemd/wifi-mode-switcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wifi-mode-switcher.service
```

Verify:

```bash
systemctl status wifi-mode-switcher.service
```

See [`wifi/README.md`](../wifi/README.md) for the full daemon behavior
(open vs. WPA2-PSK Station networks, retry/fallback, LED/matrix indicators).

## 8. Run the GUI

```bash
cd ~/Gits/RIID-gui/gui
uv run main.py
```

Open **http://localhost:8080**.

## 9. Verify the full system

- GUI loads at http://localhost:8080 (shows a "hardware disconnected"
  banner if no DAQ board is attached yet - the rest of the interface still
  works).
- The LED matrix scrolls status text; LED4 reflects the GUI's current state
  (blue/red/green/purple).
- LED3 shows white (Station mode, the default) or red (AP mode).
- Holding the WiFi button for 5+ seconds toggles LED3 and flashes a
  matching matrix message (`STA MODE - <ssid>`, `AP MODE`, or
  `STA FAILED -> AP MODE`).
