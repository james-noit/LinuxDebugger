import asyncio
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import Screen
from textual.widgets import Footer, ListView

from .commands import PANELS as BUILT_IN_PANELS, Command
from .macros import Macro, MacroOption
from .plugins import PLUGIN_CLASSES, discover_plugin_panels
from .settings import DEFAULT_KEYBINDINGS, Settings, load_settings, save_settings
from .severity import LogEntry, format_dmesg_line, format_journal_line
from .version import load_version
from .widgets.command_description import CommandDescription
from .widgets.command_list import CommandItem, CommandList
from .widgets.console import Console, Terminal
from .widgets.console_position_modal import ConsolePositionModal
from .widgets.filter_bar import FilterBar
from .widgets.flag_description import FlagDescription
from .widgets.flag_list import FlagItem, FlagList
from .widgets.flag_value_modal import FlagValueModal
from .widgets.custom_time_range_modal import CustomTimeRangeModal
from .widgets.export_modal import ExportModal
from .widgets.header import Header
from .widgets.log_entry_modal import LogEntryModal
from .widgets.log_filters import LogFilters
from .widgets.log_search_bar import LogSearchBar
from .widgets.log_macro_pane import LogMacroPane
from .widgets.log_view import LogView
from .widgets.macro_confirm_modal import MacroConfirmModal
from .widgets.macro_list import MacroList
from .widgets.macro_option_list import MacroOptionItem, MacroOptionList
from .widgets.macro_view import MacroView
from .widgets.panel_tabs import PanelTabs
from .widgets.password_modal import PasswordModal
from .widgets.sense_hat_view import SenseHatView
from .widgets.severity_filter import SeverityFilter
from .widgets.time_range_filter import TimeRangeFilter

load_version()


class LinuxDebuggerApp(App):
    """TUI for browsing and running Linux system-log commands."""

    TITLE = "Linux Debugger"
    SUB_TITLE = "log monitor"

    CSS = """
    #main-row {
        height: 1fr;
    }
    #command-pane {
        width: 42;
    }
    #log-pane {
        width: 1fr;
    }
    #log-macro-pane {
        height: 1fr;
    }
    CommandList, FlagList {
        height: 1fr;
        border: round $primary;
    }
    LogView, MacroView {
        height: 1fr;
        border: round $primary;
    }
    """

    BINDINGS = [
        ("ctrl+k", "stop_command", "Stop running command"),
        ("ctrl+l", "clear_log", "Clear log"),
        ("ctrl+e", "export_log", "Export log"),
        ("ctrl+r", "reset_filters", "Reset filters"),
        ("ctrl+d", "toggle_description", "Toggle description"),
        ("ctrl+q", "quit", "Quit"),
        # alt+c/alt+b are the documented shortcut, but terminals send Alt
        # combos as a bare Escape followed by the letter as two separate
        # bytes; if there's any delay between them (very common with real
        # keypresses, SSH, etc.) Textual can't tell that apart from the user
        # just pressing Escape, and the letter falls through as normal text
        # input instead. ctrl+right/ctrl+left are sent as a single atomic
        # escape sequence by the terminal, so they don't have this problem —
        # keep them as the reliable fallback.
        Binding("alt+c", "next_panel", "Next panel", show=False),
        Binding("alt+b", "prev_panel", "Previous panel", show=False),
        Binding("ctrl+right", "next_panel", "Next panel"),
        Binding("ctrl+left", "prev_panel", "Previous panel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._process: asyncio.subprocess.Process | None = None
        self._worker = None
        self._flag_selections: dict[tuple[str, str], set[int]] = defaultdict(set)
        self._flag_values: dict[tuple[str, str], dict[int, str]] = defaultdict(dict)
        self._macro_option_selections: dict[tuple[str, str], dict[str, bool]] = defaultdict(dict)
        self._panel_index = 0
        self._current_command_name: str | None = None
        self._show_description = True
        self._settings: Settings = load_settings()
        self._console_open = False
        self._panels = BUILT_IN_PANELS + discover_plugin_panels(PLUGIN_CLASSES)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-row"):
            with Vertical(id="command-pane"):
                yield FilterBar(id="filter-bar")
                yield CommandList(
                    self._active_panel.commands,
                    flags_provider=self._flags_for,
                    values_provider=self._values_for,
                    on_filter_changed=self._on_filter_changed,
                    id="commands",
                )
                yield CommandDescription(id="command-description")
            with Vertical(id="log-pane"):
                yield LogFilters(id="log-filters")
                yield LogSearchBar(id="log-search-bar")
                yield LogMacroPane(
                    LogView(id="log", on_search_changed=self._on_log_search_changed),
                    MacroView(id="macro-view"),
                    id="log-macro-pane",
                )
        yield Footer()

    def on_mount(self) -> None:
        self._update_panel_tabs()
        self.log_macro_pane.set_macro_available(False)
        self.run_worker(self._sync_macro_list(), exclusive=False)
        self._bind_console_key()

    def _bind_console_key(self) -> None:
        # A dynamic bind() rather than a static BINDINGS entry -- the key
        # is user-configurable (settings.keybindings), so it isn't known
        # until settings.json has been read. refresh_bindings() prompts
        # the Footer to redraw so the (possibly reconfigured) key shows up
        # there immediately rather than after the next keypress.
        self.bind(self._console_toggle_key(), "toggle_console", description="Console")
        self.refresh_bindings()

    def _console_toggle_key(self) -> str:
        return self._settings.keybindings.get("toggle_console", DEFAULT_KEYBINDINGS["toggle_console"])

    @property
    def _active_panel(self):
        return self._panels[self._panel_index]

    @property
    def log_macro_pane(self) -> LogMacroPane:
        return self.query_one("#log-macro-pane", LogMacroPane)

    def _flags_for(self, command_name: str) -> set[int]:
        return self._flag_selections[(self._active_panel.name, command_name)]

    def _values_for(self, command_name: str) -> dict[int, str]:
        return self._flag_values[(self._active_panel.name, command_name)]

    def _macro_options_for(self, macro: Macro) -> dict[str, bool]:
        state = self._macro_option_selections[(self._active_panel.name, macro.name)]
        if not state:
            # First access: seed from each option's own default rather than
            # starting all-unchecked, since "show this row" options default
            # to on (narrowing down, not building up).
            state.update({option.key: option.default for option in macro.options})
        return state

    def _selected_macro_option_keys(self, macro: Macro) -> frozenset[str]:
        state = self._macro_options_for(macro)
        return frozenset(key for key, checked in state.items() if checked)

    def _command_line(self, command: Command) -> str:
        values = self._values_for(command.name)
        tokens = [command.name, *command.base_args]
        for index in sorted(self._flags_for(command.name)):
            tokens.extend(command.flags[index].resolved_tokens(values.get(index)))
        if command.requires_sudo:
            tokens.insert(0, "sudo")
        return " ".join(tokens)

    def _on_filter_changed(self, filter_text: str) -> None:
        try:
            self.query_one("#filter-bar", FilterBar).show(filter_text)
        except NoMatches:
            pass

    def _on_log_search_changed(self, text: str, count: int) -> None:
        try:
            self.query_one("#log-search-bar", LogSearchBar).show(text, count)
        except NoMatches:
            pass

    def on_log_view_open_entry(self, message: LogView.OpenEntry) -> None:
        self.push_screen(LogEntryModal(message.text))

    def on_sense_hat_view_navigate_panel(self, message: SenseHatView.NavigatePanel) -> None:
        self.run_worker(self._switch_panel(message.direction), exclusive=False)

    def on_severity_filter_changed(self, message: SeverityFilter.Changed) -> None:
        self._apply_log_filters()

    def on_time_range_filter_changed(self, message: TimeRangeFilter.Changed) -> None:
        self._apply_log_filters()

    def on_time_range_filter_open_custom(
        self, message: TimeRangeFilter.OpenCustom
    ) -> None:
        self.run_worker(self._open_custom_time_range(), exclusive=False)

    async def _open_custom_time_range(self) -> None:
        result = await self.push_screen_wait(CustomTimeRangeModal())
        if result is None:
            return
        delta, label = result
        self.query_one("#time-range-filter", TimeRangeFilter).set_custom(delta, label)

    def _apply_log_filters(self) -> None:
        severities = self.query_one("#severity-filter", SeverityFilter).selected
        time_range = self.query_one("#time-range-filter", TimeRangeFilter).current
        self.log_view.set_filters(severities, time_range)

    def action_reset_filters(self) -> None:
        if not self.log_view.is_filtered:
            return
        self.query_one("#severity-filter", SeverityFilter).reset()
        self.query_one("#time-range-filter", TimeRangeFilter).reset()
        self.log_view.set_search("")
        self.notify("Filters cleared", timeout=2)

    def action_toggle_description(self) -> None:
        self._show_description = not self._show_description
        self.command_description.display = self._show_description
        try:
            self.query_one("#flag-description", FlagDescription).display = (
                self._show_description
            )
        except NoMatches:
            pass

    def _update_panel_tabs(self) -> None:
        self.query_one("#panel-tabs", PanelTabs).show(
            [panel.name for panel in self._panels], self._panel_index
        )

    @property
    def log_view(self) -> LogView:
        return self.query_one("#log", LogView)

    @property
    def command_description(self) -> CommandDescription:
        return self.query_one("#command-description", CommandDescription)

    @property
    def command_list(self) -> CommandList:
        return self.query_one("#commands", CommandList)

    # -- highlighting -------------------------------------------------

    def on_list_view_highlighted(self, message: ListView.Highlighted) -> None:
        if isinstance(message.list_view, CommandList):
            item = message.item
            command = item.command if isinstance(item, CommandItem) else None
            selected = self._flags_for(command.name) if command else set()
            values = self._values_for(command.name) if command else {}
            self.command_description.show(command, selected, values)
        elif isinstance(message.list_view, FlagList):
            item = message.item
            flag = item.flag if isinstance(item, FlagItem) else None
            try:
                self.query_one("#flag-description", FlagDescription).show(flag)
            except NoMatches:
                pass
        elif isinstance(message.list_view, MacroOptionList):
            item = message.item
            option = item.option if isinstance(item, MacroOptionItem) else None
            try:
                self.query_one("#macro-option-description", FlagDescription).show(option)
            except NoMatches:
                pass

    # -- panel switching --------------------------------------------------

    def action_next_panel(self) -> None:
        self.run_worker(self._switch_panel(1), exclusive=False)

    def action_prev_panel(self) -> None:
        self.run_worker(self._switch_panel(-1), exclusive=False)

    async def _switch_panel(self, direction: int) -> None:
        if len(self._panels) < 2:
            return
        if self.query("#flags"):
            await self._close_flag_picker()
        if self.query("#macro-options"):
            await self._close_macro_options()

        self._panel_index = (self._panel_index + direction) % len(self._panels)
        self._update_panel_tabs()
        # Leaving the panel invalidates any macro result shown for it, so
        # the toggle goes away entirely here (not just a view switch).
        self.log_macro_pane.set_macro_available(False)

        content_factory = self._active_panel.content_factory
        if content_factory is not None:
            await self.log_macro_pane.show_custom(content_factory)
        else:
            await self.log_macro_pane.clear_custom()

        command_list = self.command_list
        await command_list.set_commands(self._active_panel.commands)
        await self._sync_macro_list()
        # A content_factory panel's whole UI is its custom widget --
        # show_custom() above already focused it, so focusing the (empty)
        # CommandList here would just steal that focus right back and
        # silently swallow the widget's own key bindings.
        if content_factory is None:
            command_list.focus()

        item = command_list.highlighted_child
        command = item.command if isinstance(item, CommandItem) else None
        selected = self._flags_for(command.name) if command else set()
        values = self._values_for(command.name) if command else {}
        self.command_description.show(command, selected, values)

    # -- macros -----------------------------------------------------------

    async def _sync_macro_list(self) -> None:
        """Mounts/removes/replaces the Macros box so it always matches the
        active panel's own macros -- not just "present or not" (every
        panel has macros now), but swapped out entirely when switching
        between two panels that both define macros."""
        try:
            existing = self.query_one("#macros", MacroList)
        except NoMatches:
            existing = None

        macros = self._active_panel.macros
        if existing is not None and existing.macros == macros:
            return

        if existing is not None:
            await existing.remove()
        if macros:
            pane = self.query_one("#command-pane", Vertical)
            await pane.mount(MacroList(macros, id="macros"), before=self.command_description)

    def on_macro_list_run_macro(self, message: MacroList.RunMacro) -> None:
        self.run_worker(self._confirm_and_run_macro(message.macro), exclusive=False)

    async def _confirm_and_run_macro(self, macro: Macro) -> None:
        confirmed = await self.push_screen_wait(MacroConfirmModal(macro))
        if not confirmed:
            return

        selected = self._selected_macro_option_keys(macro)
        password: str | None = None
        if any(option.requires_sudo for option in macro.options if option.key in selected):
            password = await self.push_screen_wait(
                PasswordModal(macro.name, subject_label="Macro")
            )
            if password is None:
                return

        self._worker = self.run_worker(self._run_macro(macro, selected, password), exclusive=True)

    async def _run_macro(
        self, macro: Macro, selected: frozenset[str], password: str | None
    ) -> None:
        pane = self.log_macro_pane
        log_view = pane.log_view
        macro_view = pane.macro_view

        # The raw log holds the commands the macro actually ran; the macro
        # view is the parsed/templated read of that same data. Both live in
        # the same pane, flipped between with Ctrl+Right/Ctrl+Left.
        log_view.clear_log()
        log_view.border_title = f"Log output — {macro.name}"
        macro_view.border_title = f"Macro output — {macro.name}"
        macro_view.show_message(f"Running macro: {macro.name} ...")
        pane.set_macro_available(True)
        pane.show_macro()

        self.sub_title = f"running macro: {macro.name}"
        run = await (macro.run(selected, password) if macro.options else macro.run())
        log_view.append_text(run.raw_log)
        macro_view.show(run.result)
        self.sub_title = "log monitor"

    # -- macro options ----------------------------------------------------

    async def on_macro_list_open_options(self, message: MacroList.OpenOptions) -> None:
        macro = message.macro
        selections = self._macro_options_for(macro)

        # Same annex-room treatment as a command's flags: options replace
        # both Commands and Macros rather than squeezing in below them.
        self.command_list.display = False
        try:
            self.query_one("#macros", MacroList).display = False
        except NoMatches:
            pass

        pane = self.query_one("#command-pane", Vertical)
        option_list = MacroOptionList(macro, selections, id="macro-options")
        await pane.mount(option_list, before=self.command_description)
        option_description = FlagDescription(id="macro-option-description")
        await pane.mount(option_description)
        option_description.display = self._show_description

        option_list.focus()

    def on_macro_option_list_option_toggled(
        self, message: MacroOptionList.OptionToggled
    ) -> None:
        # Selections are stored by key in a plain dict already mutated by
        # the widget itself; nothing else currently mirrors that state
        # (macro list rows don't show a per-option summary the way a
        # command's flags hint does), so there's nothing further to do here
        # beyond letting the message exist for future use.
        pass

    async def on_macro_option_list_closed(self, message: MacroOptionList.Closed) -> None:
        await self._close_macro_options()

    async def _close_macro_options(self) -> None:
        try:
            await self.query_one("#macro-options", MacroOptionList).remove()
        except NoMatches:
            pass
        try:
            await self.query_one("#macro-option-description", FlagDescription).remove()
        except NoMatches:
            pass

        self.command_list.display = True
        try:
            self.query_one("#macros", MacroList).display = True
        except NoMatches:
            pass
        try:
            self.query_one("#macros", MacroList).focus()
        except NoMatches:
            self.command_list.focus()

    def _restore_log_view(self) -> None:
        # Switches the view back to the raw log without discarding a macro
        # result that might already be there -- Ctrl+Right still flips back
        # to it afterward, until the panel itself is switched away from.
        try:
            self.log_macro_pane.show_log()
        except NoMatches:
            pass

    # -- flag picker ----------------------------------------------------

    async def on_command_list_open_flags(
        self, message: CommandList.OpenFlags
    ) -> None:
        command = message.command
        selected = self._flags_for(command.name)
        values = self._values_for(command.name)

        # Flags take over the spot where Commands (and Macros, if present)
        # were -- an annex room, not another box squeezed in underneath.
        self.command_list.display = False
        try:
            self.query_one("#macros", MacroList).display = False
        except NoMatches:
            pass

        pane = self.query_one("#command-pane", Vertical)
        flag_list = FlagList(command, selected, values, id="flags")
        await pane.mount(flag_list, before=self.command_description)
        flag_description = FlagDescription(id="flag-description")
        await pane.mount(flag_description)
        flag_description.display = self._show_description

        self.command_description.show(command, selected, values)
        flag_list.focus()

    def on_flag_list_flag_toggled(self, message: FlagList.FlagToggled) -> None:
        self.command_description.show(
            message.command,
            self._flags_for(message.command.name),
            self._values_for(message.command.name),
        )
        self.command_list.refresh_flag_indicator(message.command.name)

    async def on_flag_list_customize_requested(
        self, message: FlagList.CustomizeRequested
    ) -> None:
        self.run_worker(self._customize_flag(message), exclusive=False)

    async def _customize_flag(self, message: FlagList.CustomizeRequested) -> None:
        command, flag, index = message.command, message.flag, message.flag_index
        values = self._values_for(command.name)
        current = values.get(index, flag.default_value() or "")

        value = await self.push_screen_wait(FlagValueModal(flag, current))
        if value is None:
            return

        values[index] = value
        self._flags_for(command.name).add(index)

        try:
            self.query_one("#flags", FlagList).apply_value(index, value)
        except NoMatches:
            pass
        self.command_description.show(command, self._flags_for(command.name), values)
        self.command_list.refresh_flag_indicator(command.name)

    async def on_flag_list_closed(self, message: FlagList.Closed) -> None:
        await self._close_flag_picker()

    async def _close_flag_picker(self) -> None:
        try:
            await self.query_one("#flags", FlagList).remove()
        except NoMatches:
            pass
        try:
            await self.query_one("#flag-description", FlagDescription).remove()
        except NoMatches:
            pass

        command_list = self.command_list
        command_list.display = True
        try:
            self.query_one("#macros", MacroList).display = True
        except NoMatches:
            pass
        command_list.focus()

        item = command_list.highlighted_child
        command = item.command if isinstance(item, CommandItem) else None
        selected = self._flags_for(command.name) if command else set()
        values = self._values_for(command.name) if command else {}
        self.command_description.show(command, selected, values)

    # -- running commands -------------------------------------------------

    def on_command_list_command_selected(
        self, message: CommandList.CommandSelected
    ) -> None:
        self._worker = self.run_worker(
            self._handle_command(message.command), exclusive=True
        )

    async def _handle_command(self, command: Command) -> None:
        password = None
        if command.requires_sudo:
            password = await self.push_screen_wait(
                PasswordModal(self._command_line(command))
            )
            if password is None:
                return
        await self._run_command(command, password)

    async def _run_command(self, command: Command, password: str | None) -> None:
        command_line = self._command_line(command)
        self._restore_log_view()
        self.log_view.clear_log()
        self.log_view.border_title = f"Log output — {command_line}"
        self.sub_title = f"running: {command_line}"
        self._current_command_name = command.name

        values = self._values_for(command.name)
        argv = [command.name, *command.base_args]
        for index in sorted(self._flags_for(command.name)):
            argv.extend(command.flags[index].resolved_tokens(values.get(index)))

        # journalctl and dmesg entries carry a syslog severity; ask for
        # structured/decoded output so each line can be prefixed with a
        # colored severity dot instead of showing raw, unmarked text.
        stdout_formatter = None
        if command.name == "journalctl":
            argv.extend(["-o", "json"])
            stdout_formatter = format_journal_line
        elif command.name == "dmesg":
            argv.extend(["-x", "-T"])
            stdout_formatter = format_dmesg_line

        if command.requires_sudo:
            argv = ["sudo", "-k", "-S", "-p", "", *argv]

        try:
            process = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE
                if command.requires_sudo
                else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            self.log_view.append_text(f"Command not found: {argv[0]}\n")
            self.sub_title = "log monitor"
            return

        self._process = process

        if command.requires_sudo and password is not None:
            try:
                process.stdin.write((password + "\n").encode())
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process.stdin.close()

        try:
            stdout_task = asyncio.create_task(
                self._pump_stream(process.stdout, "", stdout_formatter)
            )
            stderr_task = asyncio.create_task(self._pump_stream(process.stderr, "! "))
            await process.wait()
            await asyncio.gather(stdout_task, stderr_task)
            if process.returncode not in (0, None):
                self.log_view.append_text(
                    f"\n[process exited with code {process.returncode}]\n"
                )
        finally:
            if process.returncode is None:
                process.terminate()
            self._process = None
            self.sub_title = "log monitor"

    async def _pump_stream(
        self,
        stream: asyncio.StreamReader,
        prefix: str,
        formatter: Callable[[str], LogEntry | None] | None = None,
    ) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace")
            if formatter is not None:
                entry = formatter(text)
                if entry is None:
                    continue
                self.log_view.append_entry(entry)
                continue
            self.log_view.append_text(prefix + text if prefix else text)

    def action_stop_command(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()

    def action_clear_log(self) -> None:
        self.log_view.clear_log()

    def action_export_log(self) -> None:
        if not self.log_view.all_plain:
            self.notify("Nothing to export yet.", severity="warning")
            return
        self.run_worker(self._export_log(), exclusive=False)

    async def _export_log(self) -> None:
        log_view = self.log_view
        command_name = self._current_command_name or "log"
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_path = str(Path.home() / f"linuxdebugger-{command_name}-{timestamp}.log")

        result = await self.push_screen_wait(
            ExportModal(has_filter=log_view.is_filtered, default_path=default_path)
        )
        if result is None:
            return
        scope, path_str = result

        lines = log_view.visible_plain if scope == "filtered" else log_view.all_plain
        path = Path(path_str).expanduser()

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(lines) + "\n")
        except OSError as error:
            self.notify(f"Export failed: {error}", severity="error", timeout=6)
            return

        self.notify(f"Exported {len(lines)} lines to {path}", title="Export complete")

    # -- console ------------------------------------------------------------

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        yield from super().get_system_commands(screen)

        yield SystemCommand(
            "Close console" if self._console_open else "Open console",
            f"{'Hide' if self._console_open else 'Show'} the ad-hoc shell console "
            f"(shortcut: {self._console_toggle_key()})",
            self.action_toggle_console,
        )
        if self._settings.console_position != "bottom":
            yield SystemCommand(
                "Console position: Bottom",
                "Move the console to the bottom of the screen",
                lambda: self.run_worker(self._set_console_position("bottom"), exclusive=False),
            )
        if self._settings.console_position != "right":
            yield SystemCommand(
                "Console position: Right",
                "Move the console to the right of the screen",
                lambda: self.run_worker(self._set_console_position("right"), exclusive=False),
            )

    def action_toggle_console(self) -> None:
        self.run_worker(self._toggle_console(), exclusive=False)

    def on_terminal_exited(self, message: Terminal.Exited) -> None:
        # The shell process ended on its own (`exit`, Ctrl+D, ...) -- a
        # frozen dead terminal sitting there has no further use, so drop
        # the whole widget rather than just hiding it. The next open then
        # takes the "no console yet" branch below and spawns a fresh
        # shell instead of reusing the dead one.
        self.run_worker(self._close_console(remove=True), exclusive=False)

    async def _toggle_console(self) -> None:
        if self._console_open:
            await self._close_console()
        else:
            await self._open_console()

    async def _open_console(self) -> None:
        if self._settings.console_position is None:
            position = await self.push_screen_wait(ConsolePositionModal())
            if position is None:
                return
            self._settings.console_position = position
            save_settings(self._settings)

        console = self._console_widget()
        if console is None:
            console = Console(id="console", reserved_key=self._console_toggle_key())
            console.add_class(f"-position-{self._settings.console_position}")
            if self._settings.console_position == "right":
                await self.query_one("#main-row", Horizontal).mount(console)
            else:
                await self.screen.mount(console, before=self.query_one(Footer))
        else:
            console.display = True
        console.focus_input()
        self._console_open = True

    async def _close_console(self, *, remove: bool = False) -> None:
        console = self._console_widget()
        if console is not None:
            if remove:
                await console.remove()
            else:
                console.display = False
        self._console_open = False
        try:
            self.command_list.focus()
        except NoMatches:
            pass

    async def _set_console_position(self, position: str) -> None:
        if position == self._settings.console_position:
            return
        self._settings.console_position = position
        save_settings(self._settings)

        console = self._console_widget()
        if console is None:
            return
        # Moving between #main-row (a Horizontal, for "right") and the
        # screen itself (for "bottom") needs a remount, not just a CSS
        # class swap -- a widget's layout parent can't change in place.
        was_open = console.display
        await console.remove()
        console = Console(id="console", reserved_key=self._console_toggle_key())
        console.add_class(f"-position-{position}")
        if position == "right":
            await self.query_one("#main-row", Horizontal).mount(console)
        else:
            await self.screen.mount(console, before=self.query_one(Footer))
        console.display = was_open
        if was_open:
            console.focus_input()

    def _console_widget(self) -> Console | None:
        try:
            return self.query_one("#console", Console)
        except NoMatches:
            return None


def run() -> None:
    LinuxDebuggerApp().run()
