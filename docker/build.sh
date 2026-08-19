#!/usr/bin/env bash
# Builds the RIID GUI's Docker image for the Arduino UNO Q's linux/arm64
# target and saves it to a tarball for transfer to the board(s).
#
# Run this on a dev machine, NOT the board itself - this is the step that
# needs internet access (fetches every uv dependency) and meaningful
# transient disk space (the board's own root partition is often too tight
# for that, even when the final image itself would fit). The resulting
# tarball + docker/install.sh need no network access on the board at all.
#
# Usage: ./build.sh [output-tar-path]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT_TAR="${1:-$SCRIPT_DIR/riid-gui.tar}"

echo "Building riid-gui:local for linux/arm64 (the Arduino UNO Q's architecture)..."
docker buildx build --platform linux/arm64 -t riid-gui:local --load "$REPO_DIR"

echo "Saving to $OUT_TAR..."
docker save riid-gui:local -o "$OUT_TAR"

echo
echo "Done: $OUT_TAR ($(du -h "$OUT_TAR" | cut -f1))"
echo "Copy it to the board along with docker/install.sh and"
echo "docker/riid-gui.service, then run install.sh there, e.g.:"
echo "  scp $OUT_TAR install.sh riid-gui.service arduino@<board>:~/Gits/RIID-gui/docker/"
echo "  ssh arduino@<board> 'cd ~/Gits/RIID-gui/docker && sudo ./install.sh'"
