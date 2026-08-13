#!/usr/bin/env bash
# Renders the matching NetworkManager connection template (riid-ap or
# riid-sta) and activates it. Meant to be run as root (this repo's
# wifi_mode_daemon.py runs as root via systemd, so it calls this directly -
# see wifi/README.md for the deployment model). Both connection profiles are
# always (re)rendered from their template on every call, so credential/SSID
# changes in wifi/config/wifi_config.json take effect on the next switch
# without any leftover stale profile.
#
# Usage: switch_wifi_mode.sh <ap|sta> <ssid> [psk]
#
# psk is required for AP mode (the shared passphrase). For STA mode, an
# empty/omitted psk targets an open (passwordless) network instead of
# WPA2-PSK - see riid-sta-open.nmconnection.template.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES_DIR="$SCRIPT_DIR/../nm-templates"
CONNECTIONS_DIR="/etc/NetworkManager/system-connections"

mode="${1:-}"
ssid="${2:-}"
psk="${3:-}"

if [[ "$mode" != "ap" && "$mode" != "sta" ]]; then
    echo "Usage: $0 <ap|sta> <ssid> [psk]" >&2
    exit 1
fi

if [[ -z "$ssid" ]]; then
    echo "Error: SSID is required." >&2
    exit 1
fi

if [[ "$mode" == "ap" && -z "$psk" ]]; then
    echo "Error: AP mode requires a passphrase." >&2
    exit 1
fi

if [[ "$EUID" -ne 0 ]]; then
    echo "Error: this script must be run as root (writes to $CONNECTIONS_DIR)." >&2
    exit 1
fi

connection_id="riid-$mode"
if [[ "$mode" == "sta" && -z "$psk" ]]; then
    template_path="$TEMPLATES_DIR/riid-sta-open.nmconnection.template"
else
    template_path="$TEMPLATES_DIR/${connection_id}.nmconnection.template"
fi
target_path="$CONNECTIONS_DIR/${connection_id}.nmconnection"

if [[ ! -f "$template_path" ]]; then
    echo "Error: template not found: $template_path" >&2
    exit 1
fi

uuid="$(cat /proc/sys/kernel/random/uuid)"

tmp_path="$(mktemp)"
trap 'rm -f "$tmp_path"' EXIT

sed \
    -e "s/{{UUID}}/$uuid/g" \
    -e "s/{{SSID}}/$ssid/g" \
    -e "s/{{PSK}}/$psk/g" \
    "$template_path" > "$tmp_path"

install -m 600 -o root -g root "$tmp_path" "$target_path"

nmcli connection reload
nmcli connection up "$connection_id"
