from typing import Callable

from textual import events
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from ..commands import Command

FlagsProvider = Callable[[str], set[int]]


def _flags_hint(command: Command, selected_indices: set[int]) -> str:
    if not command.flags:
        return ""
    if not selected_indices:
        return "flags →"
    applied = " ".join(
        " ".join(command.flags[i].tokens) for i in sorted(selected_indices)
    )
    return f"{applied} →"


class CommandItem(ListItem):
    DEFAULT_CSS = """
    CommandItem Horizontal {
        width: 100%;
        height: auto;
    }
    CommandItem .cmd-name {
        width: 1fr;
    }
    CommandItem .cmd-flags-hint {
        width: auto;
        color: $text-muted;
        text-style: none;
        text-wrap: nowrap;
        text-overflow: ellipsis;
    }
    CommandItem.-has-flags .cmd-name {
        color: $success;
        text-style: bold;
    }
    CommandItem.-has-flags .cmd-flags-hint {
        color: $success;
        text-style: bold;
    }
    """

    def __init__(self, command: Command, selected_indices: set[int] | None = None) -> None:
        self.command = command
        selected_indices = selected_indices or set()
        icon = "⚠ " if command.requires_sudo else "  "
        self._name_label = Label(f"{icon}{command.name}", classes="cmd-name")
        self._hint_label = Label(
            _flags_hint(command, selected_indices), classes="cmd-flags-hint"
        )
        super().__init__(Horizontal(self._name_label, self._hint_label))
        self.set_class(bool(selected_indices), "-has-flags")

    def set_selected_flags(self, selected_indices: set[int]) -> None:
        self._hint_label.update(_flags_hint(self.command, selected_indices))
        self.set_class(bool(selected_indices), "-has-flags")


class CommandList(ListView):
    """A ListView that lets the user type-to-filter while it has focus."""

    BINDINGS = [
        Binding("right", "open_flags", "Flags", show=False),
    ]

    class CommandSelected(Message):
        def __init__(self, command: Command) -> None:
            self.command = command
            super().__init__()

    class OpenFlags(Message):
        def __init__(self, command: Command) -> None:
            self.command = command
            super().__init__()

    def __init__(
        self,
        commands: list[Command],
        flags_provider: FlagsProvider | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._all_commands = commands
        self._visible_commands: list[Command] = []
        self._flags_provider = flags_provider or (lambda _name: set())
        self.filter_text = ""
        self.border_title = "Commands"

    async def on_mount(self) -> None:
        await self._rebuild()

    async def _rebuild(self) -> None:
        needle = self.filter_text.lower()
        self._visible_commands = [
            c for c in self._all_commands if needle in c.name.lower()
        ]
        await self.clear()
        for command in self._visible_commands:
            selected = self._flags_provider(command.name)
            await self.append(CommandItem(command, selected))
        self.border_subtitle = f"filter: {self.filter_text}" if self.filter_text else ""
        if self._visible_commands:
            self.index = 0

    def refresh_flag_indicator(self, command_name: str) -> None:
        selected = self._flags_provider(command_name)
        for item in self.children:
            if isinstance(item, CommandItem) and item.command.name == command_name:
                item.set_selected_flags(selected)

    async def on_key(self, event: events.Key) -> None:
        if event.key == "backspace":
            if self.filter_text:
                self.filter_text = self.filter_text[:-1]
                await self._rebuild()
            event.stop()
        elif event.key == "escape":
            if self.filter_text:
                self.filter_text = ""
                await self._rebuild()
                event.stop()
        elif event.key == "enter":
            return
        elif event.is_printable and event.character:
            self.filter_text += event.character
            await self._rebuild()
            event.stop()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        item = event.item
        if isinstance(item, CommandItem):
            self.post_message(self.CommandSelected(item.command))

    def action_open_flags(self) -> None:
        item = self.highlighted_child
        if not isinstance(item, CommandItem):
            return
        if not item.command.flags:
            self.notify("This command has no optional flags.")
            return
        self.post_message(self.OpenFlags(item.command))
