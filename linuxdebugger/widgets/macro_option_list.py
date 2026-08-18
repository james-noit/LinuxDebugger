from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from ..macros import Macro, MacroOption


class MacroOptionItem(ListItem):
    # Same pattern as FlagItem: checked state is a CSS class rather than
    # inline markup, so the highlight's own color pairing wins when this
    # row is also the cursor row.
    DEFAULT_CSS = """
    MacroOptionItem Horizontal {
        width: 100%;
        height: auto;
    }
    MacroOptionItem .option-label {
        width: 1fr;
    }
    MacroOptionItem .option-sudo-hint {
        width: auto;
        color: $warning;
        text-style: bold;
        text-wrap: nowrap;
    }
    MacroOptionItem.-checked .option-label {
        color: $success;
        text-style: bold;
    }
    MacroOptionItem.-checked.-highlight .option-label {
        color: $block-cursor-foreground;
        text-style: bold;
    }
    """

    def __init__(self, option: MacroOption, checked: bool) -> None:
        self.option = option
        self.checked = checked
        self._label = Label(self._render_text(), classes="option-label")
        hint = Label("sudo" if option.requires_sudo else "", classes="option-sudo-hint")
        super().__init__(Horizontal(self._label, hint))
        self.set_class(checked, "-checked")

    def _render_text(self) -> str:
        box = "☒" if self.checked else "☐"
        return f"{box} {self.option.label}"

    def set_checked(self, checked: bool) -> None:
        self.checked = checked
        self._label.update(self._render_text())
        self.set_class(checked, "-checked")


class MacroOptionGroupHeader(ListItem):
    """A divider row labelling the group of options that follows it.
    Marked `disabled` so ListView's own cursor-up/cursor-down handling
    (which already skips disabled children) steps over it automatically --
    no custom navigation logic needed here."""

    DEFAULT_CSS = """
    MacroOptionGroupHeader {
        color: $text-muted;
        text-style: bold;
    }
    """

    def __init__(self, name: str) -> None:
        super().__init__(Label(name), disabled=True)


class MacroOptionList(ListView):
    """Lets the user configure a macro before running it: which output
    rows to include, and whether to elevate privileges for the steps that
    need it. The macro equivalent of a command's FlagList, minus the
    argv-token/customize machinery since a macro option changes what its
    Python run() function does rather than building an argv.
    """

    BINDINGS = [
        Binding("enter", "toggle_option", "Toggle", show=False),
        Binding("space", "toggle_option", "Toggle", show=False),
        Binding("left", "close", "Back", show=False),
        Binding("escape", "close", "Back", show=False),
    ]

    class OptionToggled(Message):
        def __init__(self, macro: Macro, option: MacroOption, checked: bool) -> None:
            self.macro = macro
            self.option = option
            self.checked = checked
            super().__init__()

    class Closed(Message):
        pass

    def __init__(self, macro: Macro, selections: dict[str, bool], **kwargs) -> None:
        super().__init__(**kwargs)
        self.macro = macro
        self.selections = selections
        self.border_title = f"Options: {macro.name}"

    def on_mount(self) -> None:
        current_group: str | None = None
        for option in self.macro.options:
            if option.group is not None and option.group != current_group:
                self.append(MacroOptionGroupHeader(option.group))
                current_group = option.group
            checked = self.selections.get(option.key, option.default)
            self.append(MacroOptionItem(option, checked))
        if self.macro.options:
            self.index = 0
            if isinstance(self.highlighted_child, MacroOptionGroupHeader):
                self.action_cursor_down()

    def action_toggle_option(self) -> None:
        item = self.highlighted_child
        if not isinstance(item, MacroOptionItem):
            return
        checked = not item.checked
        self.selections[item.option.key] = checked
        item.set_checked(checked)
        self.post_message(self.OptionToggled(self.macro, item.option, checked))

    def action_close(self) -> None:
        self.post_message(self.Closed())
