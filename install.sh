#!/usr/bin/env bash
# One-shot installer for a fresh Arduino UNO Q: downloads and installs the
# GUI's Docker service (see docker/README.md), then optionally sets up the
# WiFi mode daemon (see wifi/README.md). Run from an already-cloned
# checkout - this doesn't clone the repository itself.
#
# Usage: sudo ./install.sh [--with-wifi | --skip-wifi]
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

run_as_user() {
    # -H: without it HOME stays /root, which confuses uv's Python/cache
    # resolution and breaks package installs into the venv.
    sudo -H -u "$SUDO_USER" "$@"
}

# --- Parse flags ---
wifi_choice=""
for arg in "$@"; do
    case "$arg" in
        --with-wifi)
            if [[ "$wifi_choice" == "skip" ]]; then
                echo "Error: --with-wifi and --skip-wifi are mutually exclusive." >&2
                exit 1
            fi
            wifi_choice="with"
            ;;
        --skip-wifi)
            if [[ "$wifi_choice" == "with" ]]; then
                echo "Error: --with-wifi and --skip-wifi are mutually exclusive." >&2
                exit 1
            fi
            wifi_choice="skip"
            ;;
        *)
            echo "Error: unrecognized argument '$arg'." >&2
            echo "Usage: sudo $0 [--with-wifi | --skip-wifi]" >&2
            exit 1
            ;;
    esac
done

echo "=== RIID full-system install ==="
echo "Repository: $SCRIPT_DIR"
echo "Installing for user: $SUDO_USER"
echo

# --- 1. GUI Docker deployment (always runs, first) ---
# Needs whatever network access this board already has - the WiFi daemon
# step below can cut that off the moment it starts (see the WiFi section),
# so the download has to happen before that, not after.
GUI_TAR="$SCRIPT_DIR/docker/riid-gui.tar"
if [[ ! -f "$GUI_TAR" ]]; then
    echo "Downloading the latest published GUI image from GitHub Releases..."
    # -f: fail loudly on a non-2xx response (e.g. a private repo rejecting an
    # unauthenticated request) instead of writing the error page to $GUI_TAR
    # and only finding out minutes later when 'docker load' rejects it.
    curl -fL -o "$GUI_TAR" \
        https://github.com/imoralesgt/RIID-gui/releases/latest/download/riid-gui.tar
fi
"$SCRIPT_DIR/docker/install.sh" "$GUI_TAR"

# --- 2. WiFi mode daemon (optional, last) ---
echo
case "$wifi_choice" in
    with)  do_wifi=true ;;
    skip)  do_wifi=false ;;
    *)
        echo "The WiFi mode daemon switches this system's WiFi adapter between"
        echo "Access Point and Station mode (see wifi/README.md). Skip this on a"
        echo "laptop/desktop or any machine whose WiFi adapter should keep doing"
        echo "whatever it's already doing."
        echo
        echo "Note: accepting this restarts the daemon immediately, applying its"
        echo "default boot mode (Access Point) right away. If this system's only"
        echo "network path is the WiFi interface being reconfigured, an"
        echo "SSH/Tailscale session over that same network will be dropped the"
        echo "moment it restarts - have local/physical access ready first."
        echo
        read -rp "Set up the WiFi mode daemon on this system? [Y/n]: " reply
        reply="${reply:-Y}"
        if [[ "$reply" =~ ^[Yy] ]]; then
            do_wifi=true
        else
            do_wifi=false
        fi
        ;;
esac

if [[ "$do_wifi" == true ]]; then
    uv_bin="$(run_as_user bash -lc 'command -v uv' || true)"
    if [[ -z "$uv_bin" ]]; then
        echo "Installing uv for $SUDO_USER..."
        run_as_user bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
    fi
    "$SCRIPT_DIR/wifi/setup.sh"

    echo
    echo "Restarting the GUI service so it picks up the WiFi daemon's socket..."
    systemctl restart riid-gui.service
fi

echo
echo "=== Done ==="
echo "The GUI is reachable at http://<board-ip> (port 80)."
if [[ "$do_wifi" == true ]]; then
    echo "The WiFi mode daemon is active - it boots into Access Point mode by"
    echo "default. Join SSID IAEA_RIID_SYSXX (passphrase RIID_IAEA) and browse"
    echo "to http://10.42.0.1 to reach it that way."
else
    echo "The WiFi mode daemon was not set up - see wifi/README.md to add it"
    echo "later (sudo wifi/setup.sh)."
fi
echo "The MCU sketch (LED4/LED3/matrix status display, manual jumper AP/STA"
echo "toggle) is separate and optional, flashed from a dev computer - see"
echo "docs/provisioning.md step 4. Not required for the GUI or WiFi daemon"
echo "above."
echo "See docker/README.md and wifi/README.md for troubleshooting either"
echo "piece individually."
