#!/usr/bin/env bash
# Loads a pre-built RIID GUI image (from docker/build.sh, run on a separate
# dev machine - see there for why) and installs/starts it as a systemd
# service. Nothing here needs network access: the image tarball already has
# every dependency baked in.
#
# Usage: sudo ./install.sh [path-to-riid-gui.tar]
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
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
IMAGE_TAR="${1:-$SCRIPT_DIR/riid-gui.tar}"

if [[ ! -f "$IMAGE_TAR" ]]; then
    echo "Error: image tarball not found at $IMAGE_TAR" >&2
    echo "Build it on a dev machine with docker/build.sh first, then copy it here." >&2
    exit 1
fi

echo "=== RIID GUI Docker install ==="
echo "Repository: $REPO_DIR"
echo "Installing for user: $SUDO_USER"
echo

# --- Install Docker if missing (idempotent) ---
if ! command -v docker &> /dev/null; then
    echo "Docker not found, installing (docker.io from the Debian repos)..."
    apt-get update
    apt-get install -y docker.io
fi
systemctl enable --now docker

# --- Refuse to fight another container already holding host port 80 -
# this board may run other Docker workloads unrelated to riid-gui. ---
conflicting="$(docker ps --format '{{.Names}} {{.Ports}}' | grep -E ':80->' | grep -v '^riid-gui ' || true)"
if [[ -n "$conflicting" ]]; then
    echo "Error: host port 80 is already in use by another running container:" >&2
    echo "$conflicting" >&2
    echo "Stop it first, or edit docker/riid-gui.service's '-p 80:8080' to use a different host port." >&2
    exit 1
fi

# --- Load the pre-built image ---
echo "Loading $IMAGE_TAR..."
docker load -i "$IMAGE_TAR"

# --- Files the container bind-mounts must pre-exist as the right type -
# Docker silently creates a directory instead of a file otherwise. ---
run_as_user() {
    sudo -H -u "$SUDO_USER" "$@"
}
run_as_user mkdir -p "$REPO_DIR/gui/logs"
run_as_user touch "$REPO_DIR/gui/gui.log"

# The WiFi daemon's socket lives in its own directory
# (/var/run/riid-wifi/riid-wifi.sock), and that whole directory - not the
# socket file directly - is what gets bind-mounted below. A directory bind
# mount reflects the daemon recreating its socket file on every restart;
# bind-mounting the file itself would instead pin whatever inode existed at
# container-start time, silently going stale (ECONNREFUSED from inside the
# container) the next time the daemon restarts. Create it here in case the
# WiFi daemon hasn't been set up yet on this board.
mkdir -p /var/run/riid-wifi

# --- systemd service, pointed at this checkout ---
unit_tmp="$(mktemp)"
trap 'rm -f "$unit_tmp"' EXIT
sed \
    -e "s#^WorkingDirectory=.*#WorkingDirectory=$REPO_DIR#" \
    -e "s#/home/arduino/Gits/RIID-gui/gui/logs#$REPO_DIR/gui/logs#" \
    -e "s#/home/arduino/Gits/RIID-gui/gui/gui.log#$REPO_DIR/gui/gui.log#" \
    "$SCRIPT_DIR/riid-gui.service" > "$unit_tmp"
install -m 644 "$unit_tmp" /etc/systemd/system/riid-gui.service
echo "Installed /etc/systemd/system/riid-gui.service"

systemctl daemon-reload
systemctl enable riid-gui.service
# 'restart' alone starts it whether this is a fresh install or a re-run
# picking up a freshly loaded image - 'enable --now' followed by 'restart'
# fires two overlapping start attempts back to back, racing the container
# name on a first-ever install.
systemctl restart riid-gui.service

echo
echo "=== Done ==="
echo "The GUI is reachable at http://<board-ip> (port 80, no suffix)."
echo "Persistent data (gui/data - configuration, recordings) lives in the"
echo "'riid-gui-data' Docker volume, independent of the container itself -"
echo "see docker/README.md."
echo "After a code change: rebuild with docker/build.sh on your dev machine,"
echo "copy the new tarball here, and re-run this script (or 'docker load' +"
echo "'systemctl restart riid-gui') to pick it up."
echo
systemctl status riid-gui.service --no-pager
