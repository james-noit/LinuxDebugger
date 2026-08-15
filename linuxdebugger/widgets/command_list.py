from typing import Callable

from textual import events
from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from ..commands import Command

FlagsProvider = Callable[[str], set[int]]
ValuesProvider = Callable[[str], dict[int, str]]


def _flags_hint(
    command: Command, selected_indices: set[int], values: dict[int, str] | None = None
) -> str:
    if not command.flags:
        return ""
    if not selected_indices:
        return "flags →"
    values = values or {}
    applied = " ".join(
        " ".join(command.flags[i].resolved_tokens(values.get(i)))
        for i in sorted(selected_indices)
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

    def __init__(
        self,
        command: Command,
        selected_indices: set[int] | None = None,
        values: dict[int, str] | None = None,
    ) -> None:
        self.command = command
        selected_indices = selected_indices or set()
        icon = "⚠ " if command.requires_sudo else "  "
        self._name_label = Label(f"{icon}{command.name}", classes="cmd-name")
        self._hint_label = Label(
            _flags_hint(command, selected_indices, values), classes="cmd-flags-hint"
        )
        super().__init__(Horizontal(self._name_label, self._hint_label))
        self.set_class(bool(selected_indices), "-has-flags")

    def set_selected_flags(
        self, selected_indices: set[int], values: dict[int, str] | None = None
    ) -> None:
        self._hint_label.update(_flags_hint(self.command, selected_indices, values))
        self.set_class(bool(selected_indices), "-has-flags")


class CommandList(ListView):
    """A ListView that lets the user type-to-filter while it has focus.

    Filtering toggles the display/disabled state of the already-mounted
    items instead of destroying and recreating widgets on every keystroke —
    the latter is expensive enough (widget + CSS + layout churn) that on a
    real terminal it visibly lags behind fast typing, making the app look
    like it "freezes" a couple of keystrokes in.
    """

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
        values_provider: ValuesProvider | None = None,
        on_filter_changed: Callable[[str], None] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._all_commands = commands
        self._visible_commands: list[Command] = list(commands)
        self._flags_provider = flags_provider or (lambda _name: set())
        self._values_provider = values_provider or (lambda _name: {})
        self._on_filter_changed = on_filter_changed
        self.filter_text = ""
        self.border_title = "Commands"

    async def on_mount(self) -> None:
        await self._mount_items(self._all_commands)

    async def set_commands(self, commands: list[Command]) -> None:
        self._all_commands = commands
        self.filter_text = ""
        await self._mount_items(commands)

    async def _mount_items(self, commands: list[Command]) -> None:
        await self.clear()
        for command in commands:
            selected = self._flags_provider(command.name)
            values = self._values_provider(command.name)
            await self.append(CommandItem(command, selected, values))
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self.filter_text.lower()
        items = [item for item in self.children if isinstance(item, CommandItem)]
        first_visible_index: int | None = None
        visible_commands: list[Command] = []
        for index, item in enumerate(items):
            matches = needle in item.command.name.lower()
            item.display = matches
            item.disabled = not matches
            if matches:
                visible_commands.append(item.command)
                if first_visible_index is None:
                    first_visible_index = index
        self._visible_commands = visible_commands
        self.index = first_visible_index
        if self._on_filter_changed is not None:
            self._on_filter_changed(self.filter_text)

    def refresh_flag_indicator(self, command_name: str) -> None:
        selected = self._flags_provider(command_name)
        values = self._values_provider(command_name)
        for item in self.children:
            if isinstance(item, CommandItem) and item.command.name == command_name:
                item.set_selected_flags(selected, values)

    def on_key(self, event: events.Key) -> None:
        if event.key == "backspace":
            if self.filter_text:
                self.filter_text = self.filter_text[:-1]
                self._apply_filter()
            event.stop()
        elif event.key == "escape":
            if self.filter_text:
                self.filter_text = ""
                self._apply_filter()
                event.stop()
        elif event.key == "enter":
            return
        elif event.is_printable and event.character:
            self.filter_text += event.character
            self._apply_filter()
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
