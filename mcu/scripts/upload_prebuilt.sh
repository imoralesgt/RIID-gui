#!/usr/bin/env bash
# Uploads a pre-built binary over SSH/network, without compiling: doesn't
# need this sketch's libraries installed, only the arduino:zephyr core (for
# the arduino:zephyr:unoq board/tool definitions used to resolve the loader
# and openocd config paths via a reference sketch).
#
# Usage: upload_prebuilt.sh [binary-file]
# Defaults to the tracked mcu/prebuilt/riid_viz.elf-zsk.bin.
#
# Requires UNOQ_HOST (and usually UNOQ_PASSWORD) to be set, either in the
# environment or in mcu/.env - same as upload_fleet.sh.
set -euo pipefail

FQBN="${FQBN:-arduino:zephyr:unoq}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_common.sh"
load_env "$SCRIPT_DIR"

BINARY="${1:-$SCRIPT_DIR/../prebuilt/riid_viz.elf-zsk.bin}"
if [[ ! -f "$BINARY" ]]; then
    echo "Error: binary not found: $BINARY" >&2
    exit 1
fi

if [[ -z "${UNOQ_HOST:-}" ]]; then
    echo "Error: UNOQ_HOST is not set. Set UNOQ_HOST (and UNOQ_PASSWORD, if" >&2
    echo "your board requires one) in mcu/.env or the environment." >&2
    exit 1
fi

echo "Resolving flash tool paths (via app/riid_viz as a reference sketch)..."
resolve_flash_artifacts "$FQBN" "$SCRIPT_DIR/../app/riid_viz"

echo "Uploading to $UNOQ_HOST over SSH..."
exec "$REMOTEOCD" upload \
    -a "$UNOQ_HOST" \
    -p "${UNOQ_PASSWORD:-}" \
    -f "$OPENOCD_CFG" \
    "$LOADER" \
    "$BINARY"
