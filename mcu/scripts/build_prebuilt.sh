#!/usr/bin/env bash
# Compiles the sketch and copies the resulting binary into mcu/prebuilt/,
# for anyone who wants to flash the board without installing arduino-cli's
# arduino:zephyr core or this sketch's libraries. Re-run this after any
# change to the sketch to keep the prebuilt binary in sync.
#
# Usage: build_prebuilt.sh [sketch-dir]
set -euo pipefail

FQBN="${FQBN:-arduino:zephyr:unoq}"
SKETCH_DIR="${1:-app/riid_viz}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/_common.sh"

PREBUILT_DIR="$SCRIPT_DIR/../prebuilt"
PREBUILT_BIN="$PREBUILT_DIR/riid_viz.elf-zsk.bin"

echo "Compiling $SKETCH_DIR..."
resolve_flash_artifacts "$FQBN" "$SKETCH_DIR"

mkdir -p "$PREBUILT_DIR"
cp "$SKETCH_BIN" "$PREBUILT_BIN"
echo "Wrote $PREBUILT_BIN"
