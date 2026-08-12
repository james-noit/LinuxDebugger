import asyncio
from collections import defaultdict

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Footer, ListView

from .commands import COMMANDS, Command
from .version import load_version
from .widgets.command_description import CommandDescription
from .widgets.command_list import CommandItem, CommandList
from .widgets.flag_description import FlagDescription
from .widgets.flag_list import FlagItem, FlagList
from .widgets.header import Header
from .widgets.log_view import LogView
from .widgets.password_modal import PasswordModal

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
    CommandList, FlagList {
        height: 1fr;
        border: round $primary;
    }
    LogView {
        width: 1fr;
        border: round $primary;
    }
    """

    BINDINGS = [
        ("ctrl+k", "stop_command", "Stop running command"),
        ("ctrl+l", "clear_log", "Clear log"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._process: asyncio.subprocess.Process | None = None
        self._worker = None
        self._flag_selections: dict[str, set[int]] = defaultdict(set)

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-row"):
            with Vertical(id="command-pane"):
                yield CommandList(
                    COMMANDS,
                    flags_provider=lambda name: self._flag_selections[name],
                    id="commands",
                )
                yield CommandDescription(id="command-description")
            yield LogView(id="log")
        yield Footer()

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
            selected = self._flag_selections[command.name] if command else set()
            self.command_description.show(command, selected)
        elif isinstance(message.list_view, FlagList):
            item = message.item
            flag = item.flag if isinstance(item, FlagItem) else None
            try:
                self.query_one("#flag-description", FlagDescription).show(flag)
            except NoMatches:
                pass

    # -- flag picker ----------------------------------------------------

    async def on_command_list_open_flags(
        self, message: CommandList.OpenFlags
    ) -> None:
        command = message.command
        selected = self._flag_selections[command.name]

        self.command_list.display = False

        pane = self.query_one("#command-pane", Vertical)
        flag_list = FlagList(command, selected, id="flags")
        await pane.mount(flag_list, before=self.command_description)
        await pane.mount(FlagDescription(id="flag-description"))

        self.command_description.show(command, selected)
        flag_list.focus()

    def on_flag_list_flag_toggled(self, message: FlagList.FlagToggled) -> None:
        self.command_description.show(
            message.command, self._flag_selections[message.command.name]
        )
        self.command_list.refresh_flag_indicator(message.command.name)

    async def on_flag_list_closed(self, message: FlagList.Closed) -> None:
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
        selected = self._flag_selections[command.name] if command else set()
        self.command_description.show(command, selected)

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
            password = await self.push_screen_wait(PasswordModal(command))
            if password is None:
                return
        await self._run_command(command, password)

    async def _run_command(self, command: Command, password: str | None) -> None:
        self.log_view.clear_log()
        self.sub_title = f"running: {command.name}"

        argv = [command.name, *command.base_args]
        for index in sorted(self._flag_selections[command.name]):
            argv.extend(command.flags[index].tokens)
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
            stdout_task = asyncio.create_task(self._pump_stream(process.stdout, ""))
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

    async def _pump_stream(self, stream: asyncio.StreamReader, prefix: str) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode(errors="replace")
            self.log_view.append_text(prefix + text if prefix else text)

    def action_stop_command(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()

    def action_clear_log(self) -> None:
        self.log_view.clear_log()


def run() -> None:
    LinuxDebuggerApp().run()
