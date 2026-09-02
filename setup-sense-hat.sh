#!/usr/bin/env bash
# Sense HAT plugin setup for Linux Debugger.
#
# Checks for (and, with permission, installs/configures) everything the
# "Sensor HAT" panel needs: the `sense-hat` Python package (via uv) and the
# Raspberry Pi's I2C bus being enabled and accessible.
#
# Usage:
#   ./setup-sense-hat.sh          interactive: asks before every change
#   ./setup-sense-hat.sh --yes    non-interactive, assumes "yes" throughout
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"

if [ -t 1 ]; then
    BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'
    YELLOW=$'\033[33m'; BLUE=$'\033[34m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
    BOLD=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; CYAN=""; RESET=""
fi

info() { printf '%s[i]%s %s\n' "$BLUE" "$RESET" "$*"; }
ok()   { printf '%s[+]%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '%s[!]%s %s\n' "$YELLOW" "$RESET" "$*"; }
err()  { printf '%s[x]%s %s\n' "$RED" "$RESET" "$*" >&2; }

have_cmd() { command -v "$1" >/dev/null 2>&1; }

box() {
    local text="$1" width=60
    printf '%s┌%s┐%s\n' "$CYAN" "$(printf '─%.0s' $(seq 1 $width))" "$RESET"
    printf '%s│%s %-*s%s│%s\n' "$CYAN" "$RESET" $((width - 1)) "$text" "$CYAN" "$RESET"
    printf '%s└%s┘%s\n' "$CYAN" "$(printf '─%.0s' $(seq 1 $width))" "$RESET"
}

banner() {
    printf '%s%s' "$BOLD" "$CYAN"
    echo "Sense HAT plugin setup — Linux Debugger"
    printf '%s\n' "$RESET"
    echo
}

INTERACTIVE=1
case "${1:-}" in
    --yes) INTERACTIVE=0 ;;
    -h|--help)
        echo "Usage: $0 [--yes]"
        exit 0
        ;;
    "") ;;
    *)
        err "Unknown option: $1"
        echo "Usage: $0 [--yes]"
        exit 1
        ;;
esac

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    have_cmd sudo && SUDO="sudo"
fi

ask_yes_no() {
    local prompt="$1" default="${2:-y}" reply suffix="[Y/n]"
    [ "$default" = "n" ] && suffix="[y/N]"
    if [ "$INTERACTIVE" -eq 0 ]; then
        [ "$default" = "n" ] && return 1 || return 0
    fi
    read -r -p "$prompt $suffix " reply || true
    reply="${reply:-$default}"
    case "$reply" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

require_sudo_or_exit() {
    if [ -z "$SUDO" ] && [ "$(id -u)" -ne 0 ]; then
        err "Need root privileges (or sudo) for: $1"
        exit 1
    fi
}

# -- step 0: sanity checks -------------------------------------------------

if [ ! -x "$VENV_PYTHON" ]; then
    err "No virtual environment found at $VENV_DIR"
    err "Run ./installer.sh first, then re-run this script."
    exit 1
fi

# -- step 1: the sense-hat Python package (via uv) -------------------------

check_sense_hat_module() {
    "$VENV_PYTHON" -c "import sense_hat" >/dev/null 2>&1
}

ensure_uv() {
    if have_cmd uv; then
        ok "uv found ($(uv --version))"
        return 0
    fi
    warn "uv (the Python package installer) is not installed."
    if ! ask_yes_no "Install uv now (official installer, no sudo needed)?" y; then
        return 1
    fi
    info "Installing uv..."
    if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
        err "uv installation failed."
        return 1
    fi
    # The installer places uv in ~/.local/bin or ~/.cargo/bin, which may not
    # be on PATH yet in this shell -- pick it up directly rather than asking
    # the user to restart their shell mid-script.
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then
            export PATH="$(dirname "$candidate"):$PATH"
            break
        fi
    done
    have_cmd uv
}

install_sense_hat_package() {
    info "Installing the sense-hat Python package into $VENV_DIR"
    if ensure_uv; then
        uv pip install --python "$VENV_PYTHON" "$SCRIPT_DIR[sensehat]"
    else
        warn "Falling back to pip (uv unavailable)."
        "$VENV_PYTHON" -m pip install -e "$SCRIPT_DIR[sensehat]" -q
    fi
}

run_package_check() {
    if check_sense_hat_module; then
        ok "sense-hat Python package already installed"
        return 0
    fi
    warn "sense-hat Python package not found in $VENV_DIR"
    if ! ask_yes_no "Install it now?" y; then
        err "Cannot continue without the sense-hat package."
        exit 1
    fi
    install_sense_hat_package
    check_sense_hat_module || { err "sense-hat still not importable after install."; exit 1; }
    ok "sense-hat Python package installed"
}

# -- step 2: system configuration (I2C) ------------------------------------

find_boot_config() {
    for candidate in /boot/firmware/config.txt /boot/config.txt; do
        [ -f "$candidate" ] && { echo "$candidate"; return 0; }
    done
    return 1
}

check_i2c_enabled() {
    if have_cmd raspi-config; then
        # raspi-config's nonint get_i2c is inverted: 0 means enabled.
        [ "$($SUDO raspi-config nonint get_i2c 2>/dev/null || echo 1)" -eq 0 ]
        return $?
    fi
    local config_file
    config_file="$(find_boot_config)" || return 1
    grep -qE '^\s*dtparam=i2c_arm=on\b' "$config_file"
}

enable_i2c() {
    require_sudo_or_exit "enabling the I2C interface"
    if have_cmd raspi-config; then
        info "Enabling I2C via raspi-config"
        $SUDO raspi-config nonint do_i2c 0
        return $?
    fi
    local config_file
    if ! config_file="$(find_boot_config)"; then
        err "Could not find a boot config.txt to edit. Enable I2C manually."
        return 1
    fi
    info "Adding dtparam=i2c_arm=on to $config_file"
    if grep -qE '^\s*#\s*dtparam=i2c_arm=on\b' "$config_file"; then
        $SUDO sed -i 's/^\s*#\s*dtparam=i2c_arm=on/dtparam=i2c_arm=on/' "$config_file"
    else
        printf 'dtparam=i2c_arm=on\n' | $SUDO tee -a "$config_file" >/dev/null
    fi
}

run_i2c_config_check() {
    if ! have_cmd raspi-config && ! find_boot_config >/dev/null; then
        warn "This doesn't look like a Raspberry Pi OS boot setup -- skipping I2C config check."
        warn "If this really is a Pi, enable I2C manually (raspi-config > Interface Options > I2C)."
        return 0
    fi

    if check_i2c_enabled; then
        ok "I2C interface is enabled"
    else
        warn "I2C interface is disabled"
        if ask_yes_no "Enable I2C now (requires sudo)?" y; then
            enable_i2c && ok "I2C enabled" || { err "Failed to enable I2C."; exit 1; }
            REBOOT_NEEDED=1
        else
            err "Sense HAT needs I2C enabled to work."
            exit 1
        fi
    fi

    if [ ! -e /dev/i2c-1 ]; then
        warn "/dev/i2c-1 doesn't exist yet -- a reboot is needed for the change to take effect."
        REBOOT_NEEDED=1
    fi
}

run_group_check() {
    have_cmd getent || return 0
    getent group i2c >/dev/null 2>&1 || return 0  # no such group on this system, nothing to check

    if id -nG "$USER" 2>/dev/null | grep -qw i2c; then
        ok "$USER is already in the 'i2c' group"
        return 0
    fi

    warn "$USER is not in the 'i2c' group (needed to access /dev/i2c-1 without sudo)"
    if ask_yes_no "Add $USER to the 'i2c' group now (requires sudo)?" y; then
        require_sudo_or_exit "adding $USER to the i2c group"
        $SUDO usermod -aG i2c "$USER" && ok "Added $USER to the 'i2c' group"
        warn "Log out and back in (or reboot) for the group change to take effect."
        REBOOT_NEEDED=1
    else
        warn "Skipping -- you may need to run Linux Debugger with sudo instead."
    fi
}

# -- step 3: final verification --------------------------------------------

run_final_check() {
    if [ "${REBOOT_NEEDED:-0}" -eq 1 ]; then
        warn "A reboot is needed before the Sense HAT can be verified."
        warn "Reboot, then re-run this script (or just launch Linux Debugger)."
        return 0
    fi
    info "Verifying the Sense HAT is reachable..."
    if "$VENV_PYTHON" -c "from sense_hat import SenseHat; SenseHat().get_temperature()" >/dev/null 2>&1; then
        ok "Sense HAT detected and responding"
    else
        warn "Could not read from the Sense HAT."
        warn "Check it's seated correctly on the GPIO header, then re-run this script."
    fi
}

main() {
    banner
    REBOOT_NEEDED=0

    box "1. Python dependency"
    run_package_check
    echo

    box "2. System configuration"
    run_i2c_config_check
    run_group_check
    echo

    box "3. Verification"
    run_final_check
    echo

    ok "Sense HAT setup finished. Launch Linux Debugger and look for the 'Sensor HAT' panel."
}

main
