# Shared helpers for mcu upload scripts. Meant to be sourced, not run.

load_env() {
    local script_dir="$1"
    local env_file="$script_dir/../.env"
    if [[ -f "$env_file" ]]; then
        set -a
        # shellcheck disable=SC1090
        source "$env_file"
        set +a
    fi
}

# Compiles the sketch and resolves the artifact/tool paths remoteocd needs
# to flash over SSH, since arduino-cli's own --protocol network requires
# mDNS-discovering the board first, which doesn't traverse a VPN tunnel.
# Sets OPENOCD_CFG, LOADER, SKETCH_BIN, REMOTEOCD.
resolve_flash_artifacts() {
    local fqbn="$1" sketch_dir="$2"
    arduino-cli compile --fqbn "$fqbn" "$sketch_dir" >/dev/null

    local props
    props="$(arduino-cli compile --fqbn "$fqbn" --show-properties=expanded "$sketch_dir")"

    local get_prop
    get_prop() { grep -m1 "^$1=" <<<"$props" | cut -d'=' -f2-; }

    OPENOCD_CFG="$(get_prop build.variant.path)/$(get_prop openocd_cfg)"
    LOADER="$(get_prop upload.artifacts.loader)"
    SKETCH_BIN="$(get_prop upload.artifacts.sketch)"
    REMOTEOCD="$(get_prop tools.remoteocd_network.path)/$(get_prop tools.remoteocd_network.cmd)"
}
