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

# Cross-building for arm64 on a non-arm64 host needs QEMU emulation
# registered with the kernel, or uv sync fails with "exec format error"
# trying to run an arm64 binary. This registration lives in kernel memory,
# not on disk, so it doesn't survive a reboot and has to be redone here
# every time it's missing, regardless of whether it was ever set up before.
# Actually running a tiny arm64 container - rather than trusting
# `docker buildx inspect`'s platform list, which stays stale and reports
# arm64 as supported even after the emulator backing it is gone - is the
# only reliable way to tell whether emulation currently works.
if ! docker run --rm --platform linux/arm64 alpine:3 true >/dev/null 2>&1; then
    echo "No arm64 build support detected - registering QEMU emulation (docker run --privileged, one-time per boot)..."
    docker run --privileged --rm tonistiigi/binfmt --install all
    if ! docker run --rm --platform linux/arm64 alpine:3 true >/dev/null 2>&1; then
        echo "Error: arm64 emulation still not available after registration. Docker must be able to run --privileged containers for this to work." >&2
        exit 1
    fi
fi

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
