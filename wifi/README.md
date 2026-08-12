# Network setup (WiFi)

A standalone daemon that toggles the RIID system's onboard WiFi adapter
between **Access Point** (AP) and **Station** (STA) mode, triggered by holding a
push-button for 5+ seconds. It runs directly on the host (not inside a
container) as its own systemd service, independent of `gui/` — see
[Why a separate component](#why-a-separate-component) below.

## Hardware: wiring the button

Wire a push-button between **D13** (JDIGITAL pin 14, `PB13`) and
the adjacent **GND** pin on the JDIGITAL header (pin 15) —
`riid_viz.ino` configures `D13` as `INPUT_PULLUP`, so the button should
simply short it to ground when pressed, no external resistor needed.

## How it works

- The push-button and the two RGB/matrix indicators live on the same UNO Q
  MCU sketch the GUI already drives (`mcu/app/riid_viz/riid_viz.ino`) — see
  [`mcu/README.md`](../mcu/README.md) for the full RPC method table. This
  daemon connects to the same `Arduino_RouterBridge` Unix socket
  (`/var/run/arduino-router.sock`) as the GUI does, independently.
- The **MCU** surveys how long the button is held and only reports
  back a simple "a 5s+ hold happened" latch (`poll_wifi_button`) — this
  daemon does no timing/threshold logic, it just polls that latch
  once a second and reacts.
- On a trigger, the daemon toggles between two persistent NetworkManager
  connection profiles, `riid-ap` and `riid-sta`, rendered on demand from the
  templates in [`nm-templates/`](nm-templates) via
  [`scripts/switch_wifi_mode.sh`](scripts/switch_wifi_mode.sh).
- **AP mode**: broadcasts `IAEA_RIID_<sys_id>` (e.g. `IAEA_RIID_SYS06`) with
  the passphrase in `config/wifi_config.json`'s `ap_psk` field (defaults to
  the shared `RIID_IAEA`, same as the tracked `.example` template — override
  it there if a given deployment needs a different one). LED3 (the RGB LED
  dedicated to WiFi mode, distinct from the operating-status LED) turns red;
  the matrix shows the text `AP MODE` for a while.
- **Station mode**: connects to the SSID/passphrase in
  `config/wifi_config.json` (gitignored — copy `wifi_config.json.example` to
  get started). Leaving `sta_psk` empty targets an **open (passwordless)**
  network instead of WPA2-PSK (`nm-templates/riid-sta-open.nmconnection.template`,
  no `[wifi-security]` section) - the tracked `.example` defaults to this,
  pointed at `SEIB-GUEST`. Retries up to `max_sta_retries` times (default 3);
  if all attempts fail, falls back to AP mode - LED3 turns red and the
  matrix shows `STA FAILED -> AP MODE` for a moment, distinct from a
  normal/intentional switch to AP, so a failed connection attempt is
  visibly different from a deliberate one. A successful connection turns
  LED3 white and shows `STA MODE: <ssid>` once, so the connected network
  is visible in the matrix as well.
- Every system boots into Station mode by default; the daemon only resumes
  AP mode on startup if `riid-ap` was already the NetworkManager-active
  connection from a previous run. If no Station SSID is configured yet, it
  falls back to AP immediately (there's nothing to connect to).

## Why a separate component

`gui/` is intended to run inside a Docker container, so it shouldn't be the
operating with root privileges or reaching into host-level NetworkManager
state. This WiFi daemon is deliberately independent of `gui/` — it features its
own small RPC client (a trimmed copy of `gui/mcu_interface.py`'s
`_ArduinoBridge`) rather than importing it, and runs as root directly via
systemd rather than through a sudo operation shared with the GUI.
`gui/riid_service.py` and the rest of `gui/` are untouched by this feature.


## Layout

- `wifi_mode_daemon.py` — the daemon: RPC polling loop, mode-switch/retry/
  fallback logic, boot-default handling.
- `scripts/switch_wifi_mode.sh <ap|sta> <ssid> [psk]` — renders the matching
  template and activates it via `nmcli`. Must run as root (the daemon already
  does, via systemd). `psk` is required for `ap`; for `sta` an empty/omitted
  `psk` targets an open network instead of WPA2-PSK.
- `nm-templates/riid-ap.nmconnection.template` /
  `riid-sta.nmconnection.template` / `riid-sta-open.nmconnection.template` —
  NetworkManager keyfile templates with `{{SSID}}`/`{{PSK}}`/`{{UUID}}`
  placeholders, rendered per-switch.
- `config/wifi_config.json.example` / `config/wifi_config.json` (gitignored)
  — `sys_id` (this unit's identifier, e.g. `"SYS06"` - the tracked
  `.example` uses the placeholder `"SYSXX"`, used to build the AP SSID),
  `ap_psk` (defaults to the shared `RIID_IAEA`), `sta_ssid`, `sta_psk`
  (empty = open network), `max_sta_retries`.
- `systemd/wifi-mode-switcher.service` — unit file template; see
  [Deployment](#deployment) below.
- `pyproject.toml` / `uv.lock` — this directory's own standalone `uv`
  project definition (just the `msgpack` dependency).

## Setup

Requires Python 3, [`uv`](https://docs.astral.sh/uv/), and a Linux host
running NetworkManager. This directory is its own standalone `uv` project
(a separate `pyproject.toml`/`uv.lock`, not part of the `gui`/`utils` `uv`
workspace), with its own venv rather than using the system Python or
gui/'s venv:

```bash
cd wifi
uv sync

cp config/wifi_config.json.example config/wifi_config.json
# then edit wifi_config.json: set sys_id, sta_ssid, sta_psk
# (ap_psk already defaults to the shared RIID_IAEA - only override it if
# this deployment needs a different AP passphrase)
```

`scripts/switch_wifi_mode.sh` requires root (it writes into
`/etc/NetworkManager/system-connections/`). In production this is a
non-issue — the daemon itself runs as root via systemd (see
[Deployment](#deployment) below) — but for manually invoking or testing the
script outside the daemon (e.g. interactively as a non-root user), scope a
passwordless `sudo` rule to exactly that one script rather than granting
broader access:

```bash
sudo visudo -f /etc/sudoers.d/riid-wifi
```

Add this single line (adjust the user and path to match your deployment),
then save and exit:

```
<user> ALL=(root) NOPASSWD: /path/to/RIID-gui/wifi/scripts/switch_wifi_mode.sh
```

## Deployment

This is a host-level, system-wide change, so it's a manual provisioning
step rather than something applied automatically:

```bash
sudo cp wifi/systemd/wifi-mode-switcher.service /etc/systemd/system/
# edit the unit's WorkingDirectory/ExecStart paths if this repo isn't at
# /home/arduino/Gits/RIID-gui, or uv isn't installed under that user's home
sudo systemctl daemon-reload
sudo systemctl enable --now wifi-mode-switcher.service
```
