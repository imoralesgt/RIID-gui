#!/usr/bin/env bash
# Interactive setup for the WiFi mode daemon: writes wifi_config.json,
# installs the sudoers rule and systemd service, and starts the daemon.
#
# Usage: sudo ./setup.sh
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
    echo "Please run this script with sudo: sudo $0" >&2
    exit 1
fi

if [[ -z "${SUDO_USER:-}" ]]; then
    echo "Error: could not determine the invoking user - run via 'sudo', not as root directly." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_PATH="$SCRIPT_DIR/config/wifi_config.json"

run_as_user() {
    # -H: without it HOME stays /root, which confuses uv's Python/cache
    # resolution and breaks package installs into the venv.
    sudo -H -u "$SUDO_USER" "$@"
}

existing_value() {
    local key="$1" default="$2"
    if [[ -f "$CONFIG_PATH" ]]; then
        python3 -c '
import json, sys
key, default, path = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(path) as f:
        print(json.load(f).get(key, default))
except Exception:
    print(default)
' "$key" "$default" "$CONFIG_PATH"
    else
        echo "$default"
    fi
}

echo "=== RIID WiFi mode daemon setup ==="
echo "Repository: $SCRIPT_DIR"
echo "Installing for user: $SUDO_USER"
echo

# --- Prompts (existing config values, if any, become the defaults) ---
echo "--- Access Point mode settings ---"
default_ap_ssid="$(existing_value ap_ssid "IAEA_RIID_SYS06")"
read -rp "Access Point SSID [$default_ap_ssid]: " ap_ssid
ap_ssid="${ap_ssid:-$default_ap_ssid}"

default_ap_psk="$(existing_value ap_psk "RIID_IAEA")"
read -rp "Access Point passphrase [$default_ap_psk]: " ap_psk
ap_psk="${ap_psk:-$default_ap_psk}"

echo
echo "--- Station mode settings ---"
default_sta_ssid="$(existing_value sta_ssid "")"
read -rp "Station network SSID to connect to (leave empty to skip) [$default_sta_ssid]: " sta_ssid
sta_ssid="${sta_ssid:-$default_sta_ssid}"

sta_psk=""
if [[ -n "$sta_ssid" ]]; then
    read -rsp "Station network passphrase (leave empty for an open network): " sta_psk
    echo
fi

default_max_retries="$(existing_value max_sta_retries "3")"
read -rp "Max Station connection retries [$default_max_retries]: " max_retries
max_retries="${max_retries:-$default_max_retries}"
if ! [[ "$max_retries" =~ ^[0-9]+$ ]]; then
    echo "'$max_retries' isn't a number, using $default_max_retries instead." >&2
    max_retries="$default_max_retries"
fi
echo

# --- Write config (owned by the invoking user, not root) ---
# Boot mode always starts as AP; use the GUI to change it afterward.
if [[ -n "$sta_ssid" ]]; then
    known_networks_json="[{\"ssid\": \"$sta_ssid\", \"psk\": \"$sta_psk\"}]"
else
    known_networks_json="[]"
fi

run_as_user mkdir -p "$SCRIPT_DIR/config"
run_as_user tee "$CONFIG_PATH" > /dev/null <<EOF
{
  "mode": "ap",
  "ap_ssid": "$ap_ssid",
  "ap_psk": "$ap_psk",
  "sta_ssid": "$sta_ssid",
  "sta_psk": "$sta_psk",
  "known_networks": $known_networks_json,
  "max_sta_retries": $max_retries
}
EOF
echo "Wrote $CONFIG_PATH"

# --- Install dependencies as the invoking user (not root) ---
uv_bin="$(sudo -H -u "$SUDO_USER" bash -lc 'command -v uv' || true)"
if [[ -z "$uv_bin" ]]; then
    echo "Error: 'uv' not found for user $SUDO_USER. Install it first - see docs/provisioning.md." >&2
    exit 1
fi
# .venv may be left over from an earlier/interrupted run and no longer
# contain a working interpreter - uv sync refuses to reuse it in that case
# instead of rebuilding it, so clear it first to keep this script idempotent
# regardless of prior state. Removed as root (this script already requires
# it): a previous root-run attempt can leave root-owned files inside that
# the invoking user has no permission to delete.
rm -rf "$SCRIPT_DIR/.venv"
echo "Running 'uv sync' as $SUDO_USER..."
run_as_user "$uv_bin" sync --project "$SCRIPT_DIR"

# --- sudoers rule, scoped to the switch script only ---
switch_script="$SCRIPT_DIR/scripts/switch_wifi_mode.sh"
sudoers_tmp="$(mktemp)"
trap 'rm -f "$sudoers_tmp"' EXIT
echo "$SUDO_USER ALL=(root) NOPASSWD: $switch_script" > "$sudoers_tmp"
if visudo -cf "$sudoers_tmp" > /dev/null; then
    install -m 440 "$sudoers_tmp" /etc/sudoers.d/riid-wifi
    echo "Installed /etc/sudoers.d/riid-wifi"
else
    echo "Error: generated sudoers rule failed validation, not installed." >&2
    exit 1
fi

# --- systemd service, pointed at this checkout and this user's uv ---
unit_tmp="$(mktemp)"
trap 'rm -f "$sudoers_tmp" "$unit_tmp"' EXIT
sed \
    -e "s#^WorkingDirectory=.*#WorkingDirectory=$SCRIPT_DIR#" \
    -e "s#^ExecStart=.*#ExecStart=$uv_bin run --offline wifi_mode_daemon.py#" \
    "$SCRIPT_DIR/systemd/wifi-mode-switcher.service" > "$unit_tmp"
install -m 644 "$unit_tmp" /etc/systemd/system/wifi-mode-switcher.service
echo "Installed /etc/systemd/system/wifi-mode-switcher.service"

systemctl daemon-reload
systemctl enable --now wifi-mode-switcher.service
systemctl restart wifi-mode-switcher.service

echo
echo "=== Done ==="
echo "The GUI's Network Setup card (Hardware & Calibration tab) is the"
echo "primary way to change these settings from here on. Wiring a jumper"
echo "cable (D13 to GND) is optional, for the advanced/manual toggle path -"
echo "see wifi/README.md#hardware-wiring-the-jumper."
echo
systemctl status wifi-mode-switcher.service --no-pager
