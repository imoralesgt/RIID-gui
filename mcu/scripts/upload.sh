#!/usr/bin/env bash
# Uploads a compiled Arduino UNO Q sketch, preferring a direct USB connection
# and falling back to an SSH/network upload to the board's MPU when the
# board isn't found on any USB serial port.
#
# Usage: upload.sh [sketch-dir]
#
# SSH fallback requires UNOQ_HOST (and usually UNOQ_PASSWORD) to be set,
# either in the environment or in mcu/.env.
set -euo pipefail

FQBN="${FQBN:-arduino:zephyr:unoq}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_common.sh"
load_env "$SCRIPT_DIR"

SKETCH_DIR="${1:-$SCRIPT_DIR/../app/riid_viz}"

USB_PORT="$(arduino-cli board list --json | python3 -c "
import json, sys

fqbn = '$FQBN'
data = json.load(sys.stdin)
for entry in data.get('detected_ports', []):
    port = entry.get('port', {})
    if port.get('protocol') != 'serial':
        continue
    for board in entry.get('matching_boards', []):
        if board.get('fqbn') == fqbn:
            print(port['address'])
            sys.exit(0)
")"

if [[ -n "$USB_PORT" ]]; then
    echo "Board found on USB at $USB_PORT, uploading over serial..."
    exec arduino-cli upload --fqbn "$FQBN" --port "$USB_PORT" "$SKETCH_DIR"
fi

echo "Board not found on USB, falling back to SSH/network upload..."

if [[ -z "${UNOQ_HOST:-}" ]]; then
    echo "Error: UNOQ_HOST is not set. Set UNOQ_HOST (and UNOQ_PASSWORD, if" >&2
    echo "your board requires one) in mcu/.env or the environment to enable" >&2
    echo "the SSH fallback upload." >&2
    exit 1
fi

echo "Compiling to produce fresh build artifacts..."
resolve_flash_artifacts "$FQBN" "$SKETCH_DIR"

echo "Uploading to $UNOQ_HOST over SSH..."
exec "$REMOTEOCD" upload \
    -a "$UNOQ_HOST" \
    -p "${UNOQ_PASSWORD:-}" \
    -f "$OPENOCD_CFG" \
    "$LOADER" \
    "$SKETCH_BIN"
