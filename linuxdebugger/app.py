import asyncio
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Footer, ListView

from .commands import PANELS, Command
from .severity import LogEntry, format_dmesg_line, format_journal_line
from .version import load_version
from .widgets.command_description import CommandDescription
from .widgets.command_list import CommandItem, CommandList
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
from .widgets.log_view import LogView
from .widgets.panel_tabs import PanelTabs
from .widgets.password_modal import PasswordModal
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
    CommandList, FlagList {
        height: 1fr;
        border: round $primary;
    }
    LogView {
        height: 1fr;
        border: round $primary;
    }
    """

    BINDINGS = [
        ("ctrl+k", "stop_command", "Stop running command"),
        ("ctrl+l", "clear_log", "Clear log"),
        ("ctrl+e", "export_log", "Export log"),
        ("ctrl+r", "reset_filters", "Reset filters"),
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
        self._panel_index = 0
        self._current_command_name: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-row"):
            with Vertical(id="command-pane"):
                yield PanelTabs(id="panel-tabs")
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
                yield LogView(id="log", on_search_changed=self._on_log_search_changed)
        yield Footer()

    def on_mount(self) -> None:
        self._update_panel_tabs()

    @property
    def _active_panel(self):
        return PANELS[self._panel_index]

    def _flags_for(self, command_name: str) -> set[int]:
        return self._flag_selections[(self._active_panel.name, command_name)]

    def _values_for(self, command_name: str) -> dict[int, str]:
        return self._flag_values[(self._active_panel.name, command_name)]

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

    def _update_panel_tabs(self) -> None:
        self.query_one("#panel-tabs", PanelTabs).show(
            [panel.name for panel in PANELS], self._panel_index
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

    # -- panel switching --------------------------------------------------

    def action_next_panel(self) -> None:
        self.run_worker(self._switch_panel(1), exclusive=False)

    def action_prev_panel(self) -> None:
        self.run_worker(self._switch_panel(-1), exclusive=False)

    async def _switch_panel(self, direction: int) -> None:
        if len(PANELS) < 2:
            return
        if self.query("#flags"):
            await self._close_flag_picker()

        self._panel_index = (self._panel_index + direction) % len(PANELS)
        self._update_panel_tabs()

        command_list = self.command_list
        await command_list.set_commands(self._active_panel.commands)
        command_list.focus()

        item = command_list.highlighted_child
        command = item.command if isinstance(item, CommandItem) else None
        selected = self._flags_for(command.name) if command else set()
        values = self._values_for(command.name) if command else {}
        self.command_description.show(command, selected, values)

    # -- flag picker ----------------------------------------------------

    async def on_command_list_open_flags(
        self, message: CommandList.OpenFlags
    ) -> None:
        command = message.command
        selected = self._flags_for(command.name)
        values = self._values_for(command.name)

        self.command_list.display = False

        pane = self.query_one("#command-pane", Vertical)
        flag_list = FlagList(command, selected, values, id="flags")
        await pane.mount(flag_list, before=self.command_description)
        await pane.mount(FlagDescription(id="flag-description"))

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
                PasswordModal(command, self._command_line(command))
            )
            if password is None:
                return
        await self._run_command(command, password)

    async def _run_command(self, command: Command, password: str | None) -> None:
        command_line = self._command_line(command)
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


def run() -> None:
    LinuxDebuggerApp().run()
