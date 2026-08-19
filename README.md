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
  a NetworkManager-scoped `journalctl`), **GPU** (`nvidia-smi`,
  `rocm-smi`, `rocminfo`, `glxinfo`, `vulkaninfo`, `clinfo`, `lspci` scoped
  to display controllers, a GPU-driver-scoped `journalctl`, `radeontop`,
  `intel_gpu_top` — whichever ones apply to the machine's actual GPU vendor
  simply work, the rest report "command not found"), and **System Check**
  (no commands of its own yet — it's a macros-only panel for whole-system
  analysis, growing one check at a time; see below). The tag row showing
  all panel names lives in the header, spanning the full terminal width —
  it used to sit above the command list in the 42-column-wide left pane,
  but that started visibly overflowing once a fourth, longer panel name
  joined; the header has room to keep growing. The active panel is
  highlighted, plus the shortcuts to switch: **Ctrl+→**
  moves to the next panel, **Ctrl+←** moves back (**Alt+C** / **Alt+B** also
  work, but terminals send Alt combos as a bare Escape followed by the
  letter as two separate keystrokes, so if there's any delay between them —
  common over SSH or on a busy system — the letter falls through as filter
  text instead; Ctrl+←/→ don't have that problem, so they're the reliable
  choice and what's shown in the UI). Switching panels resets the filter and
  closes any open flag picker.
- **Macros** — some panels (currently just GPU) also show a small "Macros"
  box between the command list and the description. A macro is a fixed
  combination of commands that answers one specific debugging question in a
  single shot, rather than a single command you configure with flags.
  Navigate to it (mouse click, or **Tab**) and press **Enter** — a
  confirmation dialog lists the exact commands the macro is about to run
  before anything executes. Once confirmed, the log pane shows the raw
  output of each command the macro ran; **Ctrl+→**/**Ctrl+←** flips that
  same pane over to a "Macro output" view of that same data reduced to a
  fixed set of labelled fields — the same gesture used to switch panels in
  the Commands widget, just scoped to whichever of the two is focused, with
  a small indicator above them showing which one you're looking at. The
  toggle stays available even after running another command in the same
  panel, until you switch panels entirely. Opening a command's flags (→)
  takes over the space where the command
  list (and Macros box, if present) was, the same way it already did
  before Macros existed. A macro can have its own configurable options too
  — an "options →" hint shows next to any macro that does; press → on it
  to open them (same annex-room treatment as flags). Two kinds: "Show:"
  toggles pick which output rows to include (all on by default — the
  checkboxes narrow the result down, the opposite default of a command's
  flags), and privilege toggles marked `sudo` opt into elevating a specific
  step, prompting for your password only if one is checked when you run
  the macro. A macro with a lot of options (like Basic check) clusters them
  under muted, non-selectable group headers by functionality — arrowing
  past one skips straight to the next real option instead of landing on
  it. A macro can also appear indented with a `↳` under the one directly
  above it in the same panel's Macros box, marking it as that macro's
  narrower, standalone counterpart rather than an unrelated check — "Basic
  Firewall Check" under "Basic check" is the only one so far. Every macro
  is a kernel-first decision tree:
  sysfs/proc reads come first (no package needed at all), and every
  external tool after that is only invoked once `shutil.which` confirms
  it's actually installed — fields that stay undeterminable show as
  "unknown" rather than a guess. A macro's result renders as whichever of
  four templates best fits it: a plain label/value list, a semaphore panel
  (a colored ● per row — plain circle glyphs styled per severity, the same
  approach as the log pane's severity dot, not colored-circle emoji, which
  need an emoji font to show any color at all and render double-width
  without one, breaking alignment in plainer terminals), a pass/fail
  ladder (with the chain visibly stopping at the first broken rung), or a
  percentage gauge. A macro can also group its own rows into named
  sections within that one output — Basic check does this to keep its
  user/group audit and its firewall check visually distinct despite being
  one combined run.
  - **Logs**: **System health check** (semaphore: failed units, errors
    since boot, load average, root filesystem usage), **Memory pressure
    check** (gauge: RAM/swap usage from `/proc/meminfo`, plus an OOM-kill
    search), **Disk space diagnosis** (every real mount's usage *and*
    inode usage, via `os.statvfs` — no `df` needed), **Boot time report**
    (`systemd-analyze` breakdown if installed).
  - **Network**: **Connectivity ladder** (ladder: default route from
    `/proc/net/route` → gateway ping → internet ping → DNS resolution,
    each rung skipped once one fails), **DNS check** (semaphore: each
    configured resolver tested individually), **Listening services
    summary** (`ss -tulpn` reduced to a port → process table), **Wi-Fi
    diagnosis** (nmcli device/SSID/signal, or a sysfs fallback).
  - **GPU**: **Identify GPU information** (fields: vendor/model/driver via
    sysfs, enriched with `nvidia-smi`/ROCm/`glxinfo`/`vulkaninfo`), **GPU
    errors & resets check** (semaphore: kernel log searched for the
    detected vendor's known crash signature), **GPU utilization snapshot**
    (gauge: GPU/VRAM load, `nvidia-smi` or amdgpu sysfs counters), **Display
    session check** (Wayland/X11, resolution).
  - **System Check**: **Basic check** (semaphore: parses /etc/passwd and
    /etc/group directly for UID-0 accounts and privileged-group membership,
    plus a best-effort read of /etc/sudoers for explicit per-user grants —
    reported as "unreadable" rather than skipped when it needs root, unless
    its "Require sudo for sudoers detail" option is checked — summarizing
    how many accounts have root access and which ones. It also folds in a
    firewall check: detects whichever firewall frontend is actually
    installed — ufw/firewalld/nftables/iptables, checked in that order, so
    it doesn't assume one distro's tooling — and reports whether its
    systemd service is active and enabled at boot, both readable without
    root. The default incoming policy, whether port 80 has basic
    rate-limiting, and which of the reference ports
    (SSH/HTTP/HTTPS/IMAP/IMAPS/POP3) are explicitly allowed all need root
    to read on every backend, so those three rows stay "unknown" unless its
    separate "Require sudo to read firewall rules" option is checked. 14
    options in total, each toggling one output row except the two sudo
    ones; it's read-only throughout — it never enables, configures, or
    changes firewall policy, only reports what it finds), **Basic Firewall
    Check** (ladder: the firewall half of Basic check split out on its own,
    directly below it in the list, with the same detection logic and
    options, for re-running just that part without the user/group audit).
    More checks will be added to this panel over time.
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
- `Ctrl+D` — show/hide the "Description" box under the command list (and
  the matching "Flag" box while a flag list is open). On by default;
  hiding it gives the command list more room.
- `Ctrl+E` — export the log to a file. Asks whether to export just what's
  currently **visible** (respecting the active severity/time filters) or
  **everything** captured for the current command regardless of filters,
  plus a destination path (`Ctrl+T` inside that dialog toggles which scope
  is selected, since arrow keys are busy moving the cursor in the path
  field). Defaults to the filtered scope when a filter is active.
- `Ctrl+Q` — quit.
- **Console** (`F9` by default) — toggles a real terminal, independent of the
  curated Commands/Flags/Macros system, for running whatever one-off command
  they don't cover. It's not a captured-output command runner; it spawns the
  user's actual login shell (`$SHELL`) attached to a real pseudo-terminal, so
  everything a normal terminal gives it comes for free: the shell's own
  prompt (user, host, current directory, colors — whatever its own config
  already renders), ordinary commands' color output (which most tools only
  emit when talking to a real tty), and genuine interactivity for anything
  that needs a controlling terminal — `sudo` prompts for its password in
  place exactly like a normal terminal, `systemctl edit` can invoke
  `$EDITOR`, `less`/`vim`/`top` all work. A [pyte](https://github.com/selectel/pyte)
  virtual screen decodes the shell's output, so its escape sequences (a bare
  `clear` included) only ever repaint that virtual screen — they can't leak
  through and corrupt the real terminal Textual itself is drawing to. Every
  key is forwarded straight to the shell (arrows, Ctrl+C, Ctrl+K/Ctrl+W
  readline editing, Escape inside vim, all of it) with one deliberate
  exception: whatever key opens the console also closes it, even while it's
  focused, so there's always a way out. Opening it focuses it immediately —
  no extra click or Tab needed before typing. Exiting the shell itself
  (`exit`, Ctrl+D, the shell crashing) closes the console the same way that
  key would; reopening it after that starts a brand new shell rather than
  showing the dead one. First time you open it, it asks
  whether it should live at the **bottom** or the **right** of the screen;
  that choice is saved to `~/.config/linuxdebugger/settings.json` (or under
  `$XDG_CONFIG_HOME` if set) and reused every time after, though it can be
  changed anytime from the command palette (`Ctrl+P` → "Console position:
  Bottom"/"Right"). The same palette also lists "Open console"/"Close
  console" showing whatever its shortcut currently is. That shortcut is
  configurable too — edit `"keybindings": {"toggle_console": "..."}` in the
  same settings file using
  [Textual's key names](https://textual.textualize.io/guide/input/#key-names)
  (e.g. `"ctrl+alt+space"`), then restart the app. `F9` is the shipped
  default rather than a `Ctrl+Alt+`-style chord because, like the `Alt+C`/
  `Alt+B` panel shortcuts above, some terminals don't deliver modifier-heavy
  combinations as a single atomic sequence — function keys don't have that
  problem.

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
