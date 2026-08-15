from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from ..commands import Command, Flag


class FlagItem(ListItem):
    # Checked flags are marked via a CSS class rather than inline markup, so
    # that when the row is also the highlighted (cursor) row, the highlight's
    # own foreground/background pairing wins instead of a fixed green that
    # would be unreadable against the highlight's blue background.
    DEFAULT_CSS = """
    FlagItem Horizontal {
        width: 100%;
        height: auto;
    }
    FlagItem .flag-label {
        width: 1fr;
    }
    FlagItem .flag-customize-hint {
        width: auto;
        color: $warning;
        text-style: bold;
        text-wrap: nowrap;
    }
    FlagItem.-checked .flag-label {
        color: $success;
        text-style: bold;
    }
    FlagItem.-checked.-highlight .flag-label {
        color: $block-cursor-foreground;
        text-style: bold;
    }
    """

    def __init__(self, flag: Flag, checked: bool, value: str | None = None) -> None:
        self.flag = flag
        self.checked = checked
        self.value = value
        self._label = Label(self._render_label_text(), classes="flag-label")
        self._hint_label = Label(
            "customize ›" if flag.customizable else "", classes="flag-customize-hint"
        )
        super().__init__(Horizontal(self._label, self._hint_label))
        self.set_class(checked, "-checked")

    def _render_label_text(self) -> str:
        box = "☒" if self.checked else "☐"
        label = self.flag.resolved_label(self.value)
        return f"{box} {label}"

    def set_checked(self, checked: bool) -> None:
        self.checked = checked
        self._label.update(self._render_label_text())
        self.set_class(checked, "-checked")

    def set_value(self, value: str | None) -> None:
        self.value = value
        self._label.update(self._render_label_text())


class FlagList(ListView):
    """Lets the user toggle which flags are applied to a command.

    Flags that carry a customizable value (e.g. the "today" in "--since
    today") show a "›customize" hint; pressing Right on one opens a picker
    with proposed values plus a free-text field, rather than toggling it.
    """

    BINDINGS = [
        Binding("enter", "toggle_flag", "Toggle", show=False),
        Binding("space", "toggle_flag", "Toggle", show=False),
        Binding("right", "customize_flag", "Customize", show=False),
        Binding("left", "close", "Back", show=False),
        Binding("escape", "close", "Back", show=False),
    ]

    class FlagToggled(Message):
        def __init__(self, command: Command, flag: Flag, checked: bool) -> None:
            self.command = command
            self.flag = flag
            self.checked = checked
            super().__init__()

    class CustomizeRequested(Message):
        def __init__(self, command: Command, flag: Flag, flag_index: int) -> None:
            self.command = command
            self.flag = flag
            self.flag_index = flag_index
            super().__init__()

    class Closed(Message):
        pass

    def __init__(
        self,
        command: Command,
        selected_indices: set[int],
        values: dict[int, str] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.command = command
        self.selected_indices = selected_indices
        self.values = values if values is not None else {}
        self.border_title = f"Flags: {command.name}"

    def on_mount(self) -> None:
        for index, flag in enumerate(self.command.flags):
            self.append(
                FlagItem(flag, index in self.selected_indices, self.values.get(index))
            )
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

    def action_customize_flag(self) -> None:
        item = self.highlighted_child
        if not isinstance(item, FlagItem) or not item.flag.customizable:
            return
        index = self.command.flags.index(item.flag)
        self.post_message(self.CustomizeRequested(self.command, item.flag, index))

    def apply_value(self, flag_index: int, value: str) -> None:
        """Called by the app once the customize modal returns a value."""
        self.values[flag_index] = value
        self.selected_indices.add(flag_index)
        for item in self.children:
            if isinstance(item, FlagItem) and self.command.flags[flag_index] is item.flag:
                item.set_value(value)
                item.set_checked(True)

    def action_close(self) -> None:
        self.post_message(self.Closed())
