#!/usr/bin/env bash
# Linux Debugger installer.
#
# Usage:
#   ./installer.sh            interactive: pick auto or manual mode
#   ./installer.sh --auto     non-interactive, sensible defaults
#   ./installer.sh --manual   interactive, asks about every step
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
DEFAULT_COMMAND_NAME="debug"
DEFAULT_INSTALL_DIR="$HOME/.local/bin"

if [ -t 1 ]; then
    BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'
    YELLOW=$'\033[33m'; BLUE=$'\033[34m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
    BOLD=""; DIM=""; RED=""; GREEN=""; YELLOW=""; BLUE=""; CYAN=""; RESET=""
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
    cat <<'EOF'
   __ _                  ____       _
  / /(_)_ __  _   ___  __| _ \ ___ | |__  _   _  __ _  __ _  ___ _ __
 / / | | '_ \| | | \ \/ /  | |/ _ \| '_ \| | | |/ _` |/ _` |/ _ \ '__|
/ /__| | | | | |_| |>  <  | |  __/| |_) | |_| | (_| | (_| |  __/ |
\____/_|_| |_|\__,_/_/\_\ |_|\___||_.__/ \__,_|\__, |\__, |\___|_|
                                                 |___/ |___/
EOF
    printf '%s\n' "$RESET"
    echo "                 installer.sh — set up Linux Debugger"
    echo
}

# -- privilege handling -------------------------------------------------

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    have_cmd sudo && SUDO="sudo"
fi

# -- package manager detection ------------------------------------------

detect_pkg_manager() {
    if have_cmd apt-get; then echo apt
    elif have_cmd dnf; then echo dnf
    elif have_cmd yum; then echo yum
    elif have_cmd pacman; then echo pacman
    elif have_cmd zypper; then echo zypper
    elif have_cmd apk; then echo apk
    else echo unknown
    fi
}

pkg_install() {
    local mgr="$1"; shift
    case "$mgr" in
        apt)    $SUDO apt-get update -y && $SUDO apt-get install -y "$@" ;;
        dnf)    $SUDO dnf install -y "$@" ;;
        yum)    $SUDO yum install -y "$@" ;;
        pacman) $SUDO pacman -Sy --noconfirm "$@" ;;
        zypper) $SUDO zypper --non-interactive install "$@" ;;
        apk)    $SUDO apk add "$@" ;;
        *) return 1 ;;
    esac
}

# Translate a generic dependency name into the package name for $1's manager.
pkg_name() {
    local mgr="$1" dep="$2"
    case "$dep" in
        python3) echo python3 ;;
        python3-venv)
            case "$mgr" in
                apt) echo python3-venv ;;
                *) echo "" ;; # bundled with python3 on most other distros
            esac ;;
        python3-pip)
            case "$mgr" in
                apt|dnf|yum|zypper) echo python3-pip ;;
                pacman) echo python-pip ;;
                apk) echo py3-pip ;;
                *) echo "" ;;
            esac ;;
        clipboard)
            case "$mgr" in
                unknown) echo "" ;;
                *) echo xclip ;;
            esac ;;
    esac
}

# -- dependency checks ----------------------------------------------------

check_python()        { have_cmd python3; }
check_venv_module()   { have_cmd python3 && python3 -c "import venv" >/dev/null 2>&1; }
check_pip_module()    { have_cmd python3 && python3 -m pip --version >/dev/null 2>&1; }
check_clipboard_tool() { have_cmd wl-copy || have_cmd xclip || have_cmd xsel; }

# -- interactive helpers --------------------------------------------------

ask_yes_no() {
    local prompt="$1" default="${2:-y}" reply suffix="[Y/n]"
    [ "$default" = "n" ] && suffix="[y/N]"
    read -r -p "$prompt $suffix " reply || true
    reply="${reply:-$default}"
    case "$reply" in [Yy]*) return 0 ;; *) return 1 ;; esac
}

ask_value() {
    local prompt="$1" default="$2" reply
    read -r -p "$prompt [$default]: " reply || true
    echo "${reply:-$default}"
}

# -- setup steps ------------------------------------------------------------

run_dependency_check() {
    local mgr="$1" interactive="$2"
    local missing=()

    if check_python; then ok "python3 found"; else missing+=(python3); warn "python3 not found"; fi
    if check_venv_module; then ok "python3 venv module available"; else missing+=(python3-venv); warn "python3 venv module missing"; fi
    if check_pip_module; then ok "pip available"; else missing+=(python3-pip); warn "pip missing"; fi

    if [ "${#missing[@]}" -eq 0 ]; then
        ok "All required dependencies are already present"
        return 0
    fi

    if [ "$mgr" = "unknown" ]; then
        err "Could not detect your package manager. Please install manually: ${missing[*]}"
        exit 1
    fi

    if [ -z "$SUDO" ] && [ "$(id -u)" -ne 0 ]; then
        err "Need root privileges (or sudo) to install: ${missing[*]}"
        err "Re-run this installer as root, install sudo, or install these packages yourself."
        exit 1
    fi

    if [ "$interactive" = "1" ]; then
        if ! ask_yes_no "Install missing dependencies (${missing[*]}) using '$mgr'?" y; then
            err "Cannot continue without the required dependencies."
            exit 1
        fi
    fi

    local pkgs=() dep name
    for dep in "${missing[@]}"; do
        name="$(pkg_name "$mgr" "$dep")"
        [ -n "$name" ] && pkgs+=("$name")
    done

    if [ "${#pkgs[@]}" -gt 0 ]; then
        info "Installing: ${pkgs[*]}"
        pkg_install "$mgr" "${pkgs[@]}"
    fi

    check_python || { err "python3 still missing after install attempt."; exit 1; }
    check_venv_module || { err "python3 venv module still missing after install attempt."; exit 1; }
}

run_clipboard_check() {
    local mgr="$1" interactive="$2"

    if check_clipboard_tool; then
        ok "A system clipboard tool is already available"
        return 0
    fi

    warn "No system clipboard tool found (wl-copy / xclip / xsel)."
    warn "Linux Debugger still works without one: it falls back to the terminal's OSC52 clipboard."

    [ "$mgr" = "unknown" ] && return 0
    [ -z "$SUDO" ] && [ "$(id -u)" -ne 0 ] && return 0

    local do_install=1
    if [ "$interactive" = "1" ]; then
        ask_yes_no "Install xclip for reliable clipboard support?" y || do_install=0
    fi

    if [ "$do_install" -eq 1 ]; then
        local name
        name="$(pkg_name "$mgr" clipboard)"
        if [ -n "$name" ]; then
            info "Installing $name"
            pkg_install "$mgr" "$name" || warn "Could not install $name, continuing without it."
        fi
    fi
}

ensure_venv() {
    if [ ! -d "$VENV_DIR" ]; then
        info "Creating virtual environment at $VENV_DIR"
        python3 -m venv "$VENV_DIR"
    else
        info "Virtual environment already exists at $VENV_DIR"
    fi
}

install_app() {
    info "Installing Linux Debugger into the virtual environment"
    "$VENV_DIR/bin/pip" install --upgrade pip -q
    "$VENV_DIR/bin/pip" install -e "$SCRIPT_DIR" -q
    ok "Application installed"
}

create_wrapper() {
    local command_name="$1" install_dir="$2"
    mkdir -p "$install_dir"
    local wrapper="$install_dir/$command_name"
    cat > "$wrapper" <<WRAPPER
#!/usr/bin/env bash
exec "$VENV_DIR/bin/python" -m linuxdebugger "\$@"
WRAPPER
    chmod +x "$wrapper"
    ok "Installed launcher command '$command_name' -> $wrapper"
}

ensure_path() {
    local dir="$1"
    case ":$PATH:" in
        *":$dir:"*) ok "$dir is already on your PATH"; return 0 ;;
    esac

    warn "$dir is not on your PATH"
    local rc
    case "$(basename "${SHELL:-}")" in
        zsh) rc="$HOME/.zshrc" ;;
        bash) rc="$HOME/.bashrc" ;;
        *) rc="$HOME/.profile" ;;
    esac

    local line="export PATH=\"$dir:\$PATH\""
    if [ -f "$rc" ] && grep -qF "$line" "$rc" 2>/dev/null; then
        info "PATH entry already present in $rc"
    else
        printf '\n# Added by the Linux Debugger installer\n%s\n' "$line" >> "$rc"
        ok "Added $dir to PATH in $rc"
        warn "Restart your shell (or run: source $rc) before using the command."
    fi
}

# -- modes --------------------------------------------------------------

run_auto() {
    local mgr="$1"
    run_dependency_check "$mgr" 0
    run_clipboard_check "$mgr" 0
    ensure_venv
    install_app
    create_wrapper "$DEFAULT_COMMAND_NAME" "$DEFAULT_INSTALL_DIR"
    ensure_path "$DEFAULT_INSTALL_DIR"
    echo
    ok "Installation complete. Run '${DEFAULT_COMMAND_NAME}' to start Linux Debugger."
}

run_manual() {
    local mgr="$1"
    run_dependency_check "$mgr" 1
    echo
    run_clipboard_check "$mgr" 1
    echo
    ensure_venv
    install_app
    echo
    local command_name install_dir
    command_name="$(ask_value "Command name to launch Linux Debugger" "$DEFAULT_COMMAND_NAME")"
    install_dir="$(ask_value "Directory to install the launcher in" "$DEFAULT_INSTALL_DIR")"
    echo
    create_wrapper "$command_name" "$install_dir"
    ensure_path "$install_dir"
    echo
    ok "Installation complete. Run '${command_name}' to start Linux Debugger."
}

main() {
    banner

    local mode="${1:-}"
    case "$mode" in
        --auto) mode="auto" ;;
        --manual) mode="manual" ;;
        -h|--help)
            echo "Usage: $0 [--auto|--manual]"
            exit 0
            ;;
        "") ;;
        *)
            err "Unknown option: $mode"
            echo "Usage: $0 [--auto|--manual]"
            exit 1
            ;;
    esac

    if [ -z "$mode" ]; then
        box "How would you like to install Linux Debugger?"
        echo "  1) Auto    install everything with sensible defaults"
        echo "  2) Manual  review and choose every step"
        echo
        local choice
        read -r -p "Choose [1/2] (default 1): " choice
        case "$choice" in
            2) mode="manual" ;;
            *) mode="auto" ;;
        esac
    fi
    echo

    local mgr
    mgr="$(detect_pkg_manager)"
    info "Detected package manager: $mgr"
    echo

    if [ "$mode" = "auto" ]; then
        run_auto "$mgr"
    else
        run_manual "$mgr"
    fi
}

main "$@"
