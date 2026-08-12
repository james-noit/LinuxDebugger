# Linux Debugger

Distro-agnostic Linux system debugging tool. v1 is a TUI focused on log
monitoring; a GUI is planned for a later version.

## Install

```bash
./installer.sh
```

Runs an interactive TUI installer with two modes:

- **Auto** — installs everything with sensible defaults, no questions asked.
- **Manual** — walks through each step, asking before installing anything and
  letting you pick the launcher command name and install directory.

Either mode: detects your distro's package manager (`apt`, `dnf`, `yum`,
`pacman`, `zypper`, `apk`) and installs any missing dependencies
(`python3`, the `venv` module, `pip`, and — best-effort — a clipboard tool
like `xclip`), creates the project's virtual environment and installs the
app into it, then adds a launcher command to your `PATH` (`debug` by
default; the manual mode lets you choose a different name and location).
Run `./installer.sh --auto` or `./installer.sh --manual` to skip the initial
prompt.

Once installed, just run:

```bash
debug
```

(or whatever command name you chose in manual mode).

## Run without installing

```bash
./run.sh
```

or, from an activated virtualenv:

```bash
pip install -e .
linuxdebugger
```

## Usage

- **Left pane** — list of log commands (`journalctl`, `dmesg`, `tail`, `last`,
  `who`, `systemctl`, `uptime`), shown without flags. Use the arrow keys to
  navigate, or just start typing to filter by name. Commands marked with ⚠
  require sudo — selecting one prompts for the password (masked input) before
  running. A box under the list explains whichever command is currently
  highlighted. Commands that have optional flags show a `flags →` hint on the
  right edge of the row, and turn green once at least one of their flags is
  selected, so you can see at a glance what's about to run before pressing
  Enter.
- Press **→** on a command to open its list of optional flags (if it has
  any). Navigate with the arrows, **Enter**/**Space** toggles a flag on or
  off (checked flags show a ☒ and turn green), and **←**/**Escape** goes back
  to the command list. While the flag list is open, a second box shows the
  description of whichever flag is currently in focus, and the description
  box above updates live to preview the full command with the flags you've
  selected so far. Selections are remembered per command.
- **Right pane** — scrollable log output. Select any text with the mouse (or
  keyboard selection) and it is copied to the system clipboard automatically
  (via `wl-copy`/`xclip`/`xsel` if available, falling back to the terminal's
  OSC52 clipboard so it also works over SSH).
- `Ctrl+K` — stop the currently running command (needed for `-f`/`-w` follow
  commands, which stream forever until stopped).
- `Ctrl+L` — clear the log pane.
- `Ctrl+Q` — quit.

## Version

The app version is read from the [VERSION](VERSION) file at startup, exposed
as the `LINUXDEBUGGER_VERSION` env var, and shown in the top-right of the
header.

## Requirements

- Python 3.10+
- `textual`
- Standard Linux log tools on `PATH` (`journalctl`, `dmesg`, `tail`, etc.) —
  whichever ones exist on the current distro will simply work; missing ones
  report "command not found" in the log pane instead of crashing.
