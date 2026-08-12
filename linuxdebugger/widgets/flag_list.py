from textual.binding import Binding
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from ..commands import Command, Flag


class FlagItem(ListItem):
    # Checked flags are marked via a CSS class rather than inline markup, so
    # that when the row is also the highlighted (cursor) row, the highlight's
    # own foreground/background pairing wins instead of a fixed green that
    # would be unreadable against the highlight's blue background.
    DEFAULT_CSS = """
    FlagItem.-checked {
        color: $success;
        text-style: bold;
    }
    FlagItem.-checked.-highlight {
        color: $block-cursor-foreground;
        text-style: bold;
    }
    """

    def __init__(self, flag: Flag, checked: bool) -> None:
        self.flag = flag
        self.checked = checked
        self._label = Label(self._render_text())
        super().__init__(self._label)
        self.set_class(checked, "-checked")

    def _render_text(self) -> str:
        box = "☒" if self.checked else "☐"
        return f"{box} {self.flag.label}"

    def set_checked(self, checked: bool) -> None:
        self.checked = checked
        self._label.update(self._render_text())
        self.set_class(checked, "-checked")


class FlagList(ListView):
    """Lets the user toggle which flags are applied to a command."""

    BINDINGS = [
        Binding("enter", "toggle_flag", "Toggle", show=False),
        Binding("space", "toggle_flag", "Toggle", show=False),
        Binding("left", "close", "Back", show=False),
        Binding("escape", "close", "Back", show=False),
    ]

    class FlagToggled(Message):
        def __init__(self, command: Command, flag: Flag, checked: bool) -> None:
            self.command = command
            self.flag = flag
            self.checked = checked
            super().__init__()

    class Closed(Message):
        pass

    def __init__(self, command: Command, selected_indices: set[int], **kwargs) -> None:
        super().__init__(**kwargs)
        self.command = command
        self.selected_indices = selected_indices
        self.border_title = f"Flags: {command.name}"

    def on_mount(self) -> None:
        for index, flag in enumerate(self.command.flags):
            self.append(FlagItem(flag, index in self.selected_indices))
        if self.command.flags:
            self.index = 0

    def action_toggle_flag(self) -> None:
        item = self.highlighted_child
        if not isinstance(item, FlagItem):
            return
        index = self.command.flags.index(item.flag)
        checked = index not in self.selected_indices
        if checked:
            self.selected_indices.add(index)
        else:
            self.selected_indices.discard(index)
        item.set_checked(checked)
        self.post_message(self.FlagToggled(self.command, item.flag, checked))

    def action_close(self) -> None:
        self.post_message(self.Closed())
