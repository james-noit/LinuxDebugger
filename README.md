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

- **Left pane** — a panel of commands (see below), a filter indicator, the
  command list itself, and a description box, stacked top to bottom.
- **Panels** — commands are grouped into panels: **Logs** (`journalctl`,
  `dmesg`, `tail`, `last`, `who`, `systemctl`, `uptime`, `free`, `df`, `ps`,
  `vmstat`, `lsblk`), **Network** (`ss`, `ip`, `ping`, `tcpdump`, `nmcli`,
  a NetworkManager-scoped `journalctl`), and **GPU** (`nvidia-smi`,
  `rocm-smi`, `rocminfo`, `glxinfo`, `vulkaninfo`, `clinfo`, `lspci` scoped
  to display controllers, a GPU-driver-scoped `journalctl`, `radeontop`,
  `intel_gpu_top` — whichever ones apply to the machine's actual GPU vendor
  simply work, the rest report "command not found"). The tag row above the
  list shows all panel names,
  with the active one highlighted, plus the shortcuts to switch: **Ctrl+→**
  moves to the next panel, **Ctrl+←** moves back (**Alt+C** / **Alt+B** also
  work, but terminals send Alt combos as a bare Escape followed by the
  letter as two separate keystrokes, so if there's any delay between them —
  common over SSH or on a busy system — the letter falls through as filter
  text instead; Ctrl+←/→ don't have that problem, so they're the reliable
  choice and what's shown in the UI). Switching panels resets the filter and
  closes any open flag picker.
- Commands are shown without flags. Use the arrow keys to navigate the list,
  or just start typing to filter by name — the typed text always shows in
  the bar right above the list (`🔎 type to filter…` when empty). Commands
  marked with ⚠ require sudo — selecting one prompts for the password
  (masked input) before running. A box under the list explains whichever
  command is currently highlighted. Commands that have optional flags show a
  `flags →` hint on the right edge of the row, and turn green once at least
  one of their flags is selected, so you can see at a glance what's about to
  run before pressing Enter.
- Press **→** on a command to open its list of optional flags (if it has
  any). Navigate with the arrows, **Enter**/**Space** toggles a flag on or
  off (checked flags show a ☒ and turn green), and **←**/**Escape** goes back
  to the command list. While the flag list is open, a second box shows the
  description of whichever flag is currently in focus, and the description
  box above updates live to preview the full command with the flags you've
  selected so far. Selections are remembered per command, independently per
  panel.
- Some flags carry a value you can customize, marked with a `›customize`
  hint (e.g. `-p err` or `--since today`). Pressing **→** on one of these
  opens a picker: choose from a short list of common values, or type your
  own and press Enter — either way the flag is applied with that exact
  value. Escape cancels without changing anything.
- Once you press **Enter** to run a command, the header shows the exact
  command line that was launched, including every flag and any customized
  values, so there's never a guess about what's actually executing.
- **Right pane** — a "Filters" bar, a search bar, then the scrollable log
  itself. Select text with the mouse (or keyboard selection) and it's copied
  to the system clipboard automatically (via `wl-copy`/`xclip`/`xsel` if
  available, falling back to the terminal's OSC52 clipboard so it also works
  over SSH). A plain click (no drag) on a single line copies just that line
  and shows a notification confirming what was copied.
- Click the log pane and just start typing to **search** it by word/phrase —
  the bar above the log shows what you've typed and how many lines match
  (`🔎 docker▏  (4 matches)`). Backspace edits it, Escape clears it. Search
  stacks with the severity/time filters (all three narrow the same view
  together) and, like them, only really filters `journalctl`/`dmesg` lines
  meaningfully since everything else is just matched against its raw text.
- With the log pane focused, **↑/↓** move a selection cursor between visible
  entries — marked with a `▶` and highlighted — instead of scrolling
  line-by-line, and **Enter** opens the selected entry in a detail view —
  handy for a long line that's cut off — with its own **Copy** action (`C`
  or `Enter`).
- `journalctl` and `dmesg` entries are shown with a colored severity dot (○)
  in front of each line — red for emerg/alert/crit/err, yellow for warning,
  cyan for notice, green for info, gray for debug — read from the entry's
  syslog severity, so it's obvious at a glance which lines matter, even
  scrolling through a busy `-f`/`-w` stream.
- The **Filters** bar has two focusable boxes, each showing its own shortcut
  hint on its border so the interaction doesn't need to be guessed:
  - **Severity** (`←→ move · ⏎ toggle`) — a row of the 8 syslog severities;
    move between them and toggle any combination on with Enter/Space (e.g.
    Error + Warning together). No severity toggled on means "All" (shown as
    an explicit label, not just a blank row).
  - **Time range** (`←→ presets · ⏎ custom`) — cycles through All time /
    Last 5 min / 15 min / hour / 24 hours / 7 days as you arrow through them
    (applied immediately, live-preview style); "Last 5 min" keeps sliding
    forward as time passes during a live `-f`/`-w` stream. Enter always
    opens a custom range prompt regardless of the current preset — type a
    number (minutes) or a number with a unit, e.g. `45m`, `2h`, `3d`.

  Both filters apply retroactively to everything already captured for the
  current command, not just new lines, and only affect `journalctl`/`dmesg`
  output — anything else (which has no severity or timestamp to check)
  always stays visible regardless of the filters. Filters stay set until you
  change them, including across different commands. `Ctrl+R` clears the
  severity filter, time range, *and* the search box at once, from anywhere —
  no need to focus any of them first.
- `Ctrl+→` / `Ctrl+←` (or `Alt+C` / `Alt+B`) — switch to the next / previous
  command panel.
- `Ctrl+K` — stop the currently running command (needed for `-f`/`-w` follow
  commands, which stream forever until stopped).
- `Ctrl+L` — clear the log pane.
- `Ctrl+E` — export the log to a file. Asks whether to export just what's
  currently **visible** (respecting the active severity/time filters) or
  **everything** captured for the current command regardless of filters,
  plus a destination path (`Ctrl+T` inside that dialog toggles which scope
  is selected, since arrow keys are busy moving the cursor in the path
  field). Defaults to the filtered scope when a filter is active.
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
