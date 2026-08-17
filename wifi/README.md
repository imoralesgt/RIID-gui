# Network setup (WiFi)

A standalone daemon that switches the RIID system's onboard WiFi adapter
between **Access Point** (AP) and **Station** (STA) mode. The primary control
is the GUI's *Network Setup* card (Hardware & Calibration tab), which talks to
this daemon over a local socket; a jumper cable wired to the MCU is a
secondary, advanced/manual toggle for when the GUI isn't reachable - see
[Hardware: wiring the jumper](#hardware-wiring-the-jumper) below. The daemon
runs directly on the host (not inside a container) as its own systemd
service, independent of `gui/` — see
[Why a separate component](#why-a-separate-component) below.

## Hardware: wiring the jumper

Wire a momentary jumper/button between **D13** (JDIGITAL pin 14, `PB13`) and
the adjacent **GND** pin on the JDIGITAL header (pin 15) —
`riid_viz.ino` configures `D13` as `INPUT_PULLUP`, so bridging it to ground
for 5+ seconds is all that's needed, no external resistor required. This is
optional: the GUI's Network Setup card covers the same functionality without
any wiring.

## How it works

- **GUI control (primary)**: `wifi_mode_daemon.py` listens on a second local
  Unix socket, `/var/run/riid-wifi.sock`, using the same lightweight
  msgpack-rpc framing as the Arduino RPC bridge below. `gui/wifi_interface.py`'s
  `WifiInterface` is the GUI-side client, used by `gui/view_network.py`'s
  Network Setup card. Three request methods: `get_state` (current mode, AP
  SSID/passphrase, known Station networks, last switch outcome),
  `scan_networks` (proxies an `nmcli` scan), and `apply_config` (writes new
  settings to `config/wifi_config.json` and triggers the mode switch). The
  GUI never touches `nmcli`, NetworkManager, or `sudo` itself - this socket is
  the only channel through which it affects WiFi state, so it works the same
  way whether the GUI runs directly on the host or, later, inside a Docker
  container with no host network/root access.
- **Jumper control (advanced/manual)**: the jumper and the two RGB/matrix
  indicators live on the same UNO Q MCU sketch the GUI already drives
  (`mcu/app/riid_viz/riid_viz.ino`) — see [`mcu/README.md`](../mcu/README.md)
  for the full RPC method table. This daemon connects to the same
  `Arduino_RouterBridge` Unix socket (`/var/run/arduino-router.sock`) as the
  GUI does, independently. The **MCU** surveys how long the jumper is held
  and only reports back a simple "a 5s+ hold happened" latch
  (`poll_wifi_button`) — this daemon does no timing/threshold logic, it just
  polls that latch once a second and toggles mode on a trigger.
- Either path ends up calling the same mode-switch logic, which toggles
  between two persistent NetworkManager connection profiles, `riid-ap` and
  `riid-sta`, rendered on demand from the templates in
  [`nm-templates/`](nm-templates) via
  [`scripts/switch_wifi_mode.sh`](scripts/switch_wifi_mode.sh).
- **AP mode**: broadcasts whatever SSID is in `config/wifi_config.json`'s
  `ap_ssid` field, with the passphrase in `ap_psk` (defaults to the shared
  `RIID_IAEA`). The GUI composes `ap_ssid` from a user-editable name (up to
  24 characters) plus this system's `SYS-ID` (from the GUI's own hardware
  profile), always appended as a suffix - e.g. a name of `IAEA_RIID` on
  system `SYS06` becomes `IAEA_RIID_SYS06`. LED3 (the RGB LED dedicated to
  WiFi mode, distinct from the operating-status LED) turns red; the matrix
  shows the text `AP MODE` for a while.
- **Station mode**: connects to whichever known network is selected as
  `sta_ssid`/`sta_psk` in `config/wifi_config.json` (gitignored — copy
  `wifi_config.json.example` to get started, or use the GUI's Network Setup
  card, which manages a `known_networks` list and lets the operator pick
  which one is active). Leaving a network's passphrase empty targets an
  **open (passwordless)** network instead of WPA2-PSK
  (`nm-templates/riid-sta-open.nmconnection.template`, no `[wifi-security]`
  section). Retries up to `max_sta_retries` times (default 3); if all
  attempts fail, falls back to AP mode - LED3 turns red and the matrix shows
  `STA FAILED -> AP MODE` for a moment, distinct from a normal/intentional
  switch to AP, so a failed connection attempt is visibly different from a
  deliberate one. A successful connection turns LED3 white and shows
  `STA MODE: <ssid>` once, so the connected network is visible in the matrix
  as well.
- Every system boots into the mode recorded in `config/wifi_config.json`'s
  `mode` field (`"ap"` or `"sta"`), defaulting to **Access Point** - matching
  how commercial portable spectroscopy systems behave, and avoiding a
  boot-time dependency on a Station network being reachable. The GUI updates
  this field every time the operator applies a change, so the system always
  boots back into whichever mode was last explicitly selected.

## Why a separate component

`gui/` is intended to run inside a Docker container, so it shouldn't be
operating with root privileges or reaching into host-level NetworkManager
state. This WiFi daemon is deliberately independent of `gui/` — it features its
own small RPC client (a trimmed copy of `gui/mcu_interface.py`'s
`_ArduinoBridge`) rather than importing it, and runs as root directly via
systemd rather than through a sudo operation shared with the GUI. The GUI
reaches it only through the local socket described above - the same
containerization-friendly pattern already used for the Arduino RPC bridge.
`gui/riid_service.py` and the rest of `gui/` are otherwise untouched by this
feature.


## Layout

- `wifi_mode_daemon.py` — the daemon: the GUI-facing socket server, the
  jumper's RPC polling loop, mode-switch/retry/fallback logic, and
  boot-default handling.
- `scripts/switch_wifi_mode.sh <ap|sta> <ssid> [psk]` — renders the matching
  template and activates it via `nmcli`. Must run as root (the daemon already
  does, via systemd). `psk` is required for `ap`; for `sta` an empty/omitted
  `psk` targets an open network instead of WPA2-PSK.
- `nm-templates/riid-ap.nmconnection.template` /
  `riid-sta.nmconnection.template` / `riid-sta-open.nmconnection.template` —
  NetworkManager keyfile templates with `{{SSID}}`/`{{PSK}}`/`{{UUID}}`
  placeholders, rendered per-switch.
- `config/wifi_config.json.example` / `config/wifi_config.json` (gitignored)
  — `mode` (`"ap"` or `"sta"`, applied at every daemon startup), `ap_ssid`
  (the full Access Point SSID - the GUI composes and writes this), `ap_psk`
  (defaults to the shared `RIID_IAEA`), `sta_ssid`/`sta_psk` (the currently
  active Station network), `known_networks` (the full list the GUI's picker
  offers, `[{"ssid": ..., "psk": ...}, ...]`), `max_sta_retries`.
- `systemd/wifi-mode-switcher.service` — unit file template; see
  [Manual setup](#manual-setup) below.
- `pyproject.toml` / `uv.lock` — this directory's own standalone `uv`
  project definition (just the `msgpack` dependency).
- `setup.sh` — interactive setup script; see [Setup](#setup) below.

## Setup

Requires Python 3, [`uv`](https://docs.astral.sh/uv/), and a Linux host
running NetworkManager. This directory is its own standalone `uv` project
(a separate `pyproject.toml`/`uv.lock`, not part of the `gui`/`utils` `uv`
workspace), with its own venv rather than using the system Python or
gui/'s venv.

```bash
cd wifi
sudo ./setup.sh
```

Prompts for the Access Point SSID/passphrase, then the Station network
SSID/passphrase, writes `config/wifi_config.json` (boot mode always starts as
Access Point - use the GUI afterward to switch it), runs `uv sync` as the
invoking user (not root, so the resulting `.venv` stays owned by that user),
installs the `/etc/sudoers.d/riid-wifi` rule and the
`wifi-mode-switcher.service` unit with paths pointed at this checkout, and
starts the daemon. Re-running it is safe: existing config values are offered
as defaults, and the service is reinstalled/restarted with the new values.

> **Note:** restarting the daemon applies `mode` from
> `config/wifi_config.json` immediately (defaulting to Access Point on a
> fresh setup). If this system's only network path is the WiFi interface
> being reconfigured, an SSH/Tailscale session over that same network will
> be dropped the moment the service restarts - have local/physical access
> (or the jumper cable) ready before running this remotely.

### Manual setup

Equivalent to what `setup.sh` does, run by hand:

```bash
cd wifi
uv sync

cp config/wifi_config.json.example config/wifi_config.json
```

Edit `config/wifi_config.json` and set:

- `ap_ssid` — this system's Access Point SSID (e.g. `"IAEA_RIID_SYS06"`).
- `sta_ssid` — the SSID of the network this system should connect to in
  Station mode (e.g. `"SEIB-GUEST"`).
- `sta_psk` — that network's WPA2 passphrase, or `""` (empty string) if the
  network is open/passwordless.

Leave `mode`, `ap_psk`, `known_networks`, and `max_sta_retries` at their
defaults (`"ap"`, `"RIID_IAEA"`, `[]`, and `3`) unless this deployment
specifically needs different values.

`scripts/switch_wifi_mode.sh` requires root (it writes into
`/etc/NetworkManager/system-connections/`). In production this is a
non-issue — the daemon itself runs as root via systemd — but for manually
invoking or testing the script outside the daemon (e.g. interactively as a
non-root user), scope a passwordless `sudo` rule to exactly that one script
rather than granting broader access:

```bash
sudo visudo -f /etc/sudoers.d/riid-wifi
```

Add this single line (adjust the user and path to match your deployment),
then save and exit:

```
<user> ALL=(root) NOPASSWD: /path/to/RIID-gui/wifi/scripts/switch_wifi_mode.sh
```

Install and start the systemd service - this is a host-level, system-wide
change, so it's a manual step rather than something `uv sync` applies
automatically:

```bash
sudo cp wifi/systemd/wifi-mode-switcher.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wifi-mode-switcher.service
```

If the repository was cloned somewhere other than `~/Gits/RIID-gui`, or if
`uv` was installed under a different user's home directory, edit the
installed unit's `WorkingDirectory` and `ExecStart` lines to match before
running the commands above, for example:

```
WorkingDirectory=/home/arduino/Gits/RIID-gui/wifi
ExecStart=/home/arduino/.local/bin/uv run --offline wifi_mode_daemon.py
```
