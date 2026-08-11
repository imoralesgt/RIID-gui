#!/usr/bin/env bash
# Uploads the same compiled sketch to a fleet of remote UNO Q boards over
# SSH. Boards are listed one hostname per line in mcu/boards.txt (or
# $BOARDS_FILE), all sharing UNOQ_PASSWORD from mcu/.env.
#
# Usage: upload_fleet.sh [sketch-dir]
set -euo pipefail

FQBN="${FQBN:-arduino:zephyr:unoq}"
SKETCH_DIR="${1:-.}"
UPLOAD_TIMEOUT="${UPLOAD_TIMEOUT:-20}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_common.sh"
load_env "$SCRIPT_DIR"

BOARDS_FILE="${BOARDS_FILE:-$SCRIPT_DIR/../boards.txt}"
if [[ ! -f "$BOARDS_FILE" ]]; then
    echo "Error: boards file not found at $BOARDS_FILE." >&2
    echo "Create it with one board hostname per line (see boards.txt.example)." >&2
    exit 1
fi

if [[ -z "${UNOQ_PASSWORD:-}" ]]; then
    echo "Error: UNOQ_PASSWORD is not set. Set it in mcu/.env." >&2
    exit 1
fi

mapfile -t HOSTS < <(grep -vE '^\s*(#|$)' "$BOARDS_FILE")
if [[ ${#HOSTS[@]} -eq 0 ]]; then
    echo "Error: no boards listed in $BOARDS_FILE." >&2
    exit 1
fi

echo "Compiling to produce fresh build artifacts..."
resolve_flash_artifacts "$FQBN" "$SKETCH_DIR"

FAILED=()
for host in "${HOSTS[@]}"; do
    echo ""
    echo "=== Uploading to $host ==="
    if timeout -k 5s "${UPLOAD_TIMEOUT}s" "$REMOTEOCD" upload -a "$host" -p "$UNOQ_PASSWORD" -f "$OPENOCD_CFG" "$LOADER" "$SKETCH_BIN"; then
        echo "OK: $host"
    else
        status=$?
        if [[ $status -eq 124 ]]; then
            echo "TIMEOUT: $host (no response after ${UPLOAD_TIMEOUT}s)" >&2
        else
            echo "FAILED: $host" >&2
        fi
        FAILED+=("$host")
    fi
done

echo ""
if [[ ${#FAILED[@]} -gt 0 ]]; then
    echo "Failed boards: ${FAILED[*]}" >&2
    exit 1
fi
echo "All ${#HOSTS[@]} board(s) updated successfully."
