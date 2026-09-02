#!/usr/bin/env bash
# Linux Debugger uninstaller -- undoes what installer.sh did.
#
# Usage:
#   ./uninstall.sh          interactive: asks before removing anything
#   ./uninstall.sh --yes    non-interactive, removes everything
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/linuxdebugger"
PATH_MARKER="# Added by the Linux Debugger installer"

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

box() {
    local text="$1" width=60
    printf '%s┌%s┐%s\n' "$CYAN" "$(printf '─%.0s' $(seq 1 $width))" "$RESET"
    printf '%s│%s %-*s%s│%s\n' "$CYAN" "$RESET" $((width - 1)) "$text" "$CYAN" "$RESET"
    printf '%s└%s┘%s\n' "$CYAN" "$(printf '─%.0s' $(seq 1 $width))" "$RESET"
}

banner() {
    printf '%s%s' "$BOLD" "$CYAN"
    echo "uninstall.sh — remove Linux Debugger"
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

# -- step 1: launcher command ----------------------------------------------

find_wrappers() {
    # A wrapper created by installer.sh always execs this exact venv's
    # python -- grepping for that path finds only wrappers for *this*
    # install, not unrelated commands that happen to share a bin dir.
    local marker="$VENV_DIR/bin/python"
    local candidate_dirs=("$HOME/.local/bin" "/usr/local/bin" "$HOME/bin")
    local dir file
    for dir in "${candidate_dirs[@]}"; do
        [ -d "$dir" ] || continue
        for file in "$dir"/*; do
            [ -f "$file" ] || continue
            grep -qF "$marker" "$file" 2>/dev/null && echo "$file"
        done
    done
}

remove_wrappers() {
    local wrappers
    wrappers="$(find_wrappers)"
    if [ -z "$wrappers" ]; then
        ok "No launcher command found"
        return 0
    fi

    info "Found launcher command(s):"
    printf '%s\n' "$wrappers" | while IFS= read -r wrapper; do echo "    $wrapper"; done

    if ! ask_yes_no "Remove these launcher command(s)?" y; then
        warn "Keeping launcher command(s)."
        return 0
    fi
    printf '%s\n' "$wrappers" | while IFS= read -r wrapper; do
        rm -f "$wrapper" && ok "Removed $wrapper"
    done
}

# -- step 2: PATH entry added by the installer ------------------------------

remove_path_entries() {
    local rc found_any=0
    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        [ -f "$rc" ] || continue
        grep -qF "$PATH_MARKER" "$rc" 2>/dev/null || continue
        found_any=1
        if ! ask_yes_no "Remove the PATH entry the installer added to $rc?" y; then
            warn "Keeping PATH entry in $rc."
            continue
        fi
        local tmp
        tmp="$(mktemp)"
        # Drops the marker comment line and the one line right after it
        # (the `export PATH=...` line installer.sh always writes
        # together with the marker) -- everything else in the file is
        # left untouched.
        awk -v marker="$PATH_MARKER" '
            $0 == marker { skip = 1; next }
            skip > 0 { skip--; next }
            { print }
        ' "$rc" > "$tmp"
        mv "$tmp" "$rc"
        ok "Removed PATH entry from $rc"
    done
    [ "$found_any" -eq 0 ] && ok "No installer-added PATH entries found"
    return 0
}

# -- step 3: virtual environment ---------------------------------------------

remove_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        ok "No virtual environment found at $VENV_DIR"
        return 0
    fi
    if ask_yes_no "Remove the virtual environment at $VENV_DIR?" y; then
        rm -rf "$VENV_DIR"
        ok "Removed $VENV_DIR"
    else
        warn "Keeping $VENV_DIR"
    fi
}

# -- step 4: saved settings ---------------------------------------------------

remove_settings() {
    if [ ! -d "$CONFIG_DIR" ]; then
        ok "No settings directory found at $CONFIG_DIR"
        return 0
    fi
    if ask_yes_no "Also remove saved settings/preferences at $CONFIG_DIR?" n; then
        rm -rf "$CONFIG_DIR"
        ok "Removed $CONFIG_DIR"
    else
        info "Keeping $CONFIG_DIR"
    fi
}

main() {
    banner

    box "1. Launcher command"
    remove_wrappers
    echo

    box "2. PATH entry"
    remove_path_entries
    echo

    box "3. Virtual environment"
    remove_venv
    echo

    box "4. Saved settings"
    remove_settings
    echo

    ok "Linux Debugger has been uninstalled."
    info "The source directory ($SCRIPT_DIR) was left in place -- remove it yourself (e.g. rm -rf) if you don't need it anymore."
}

main
