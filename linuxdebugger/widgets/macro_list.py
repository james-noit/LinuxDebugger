from textual.binding import Binding
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from ..macros import Macro


class MacroItem(ListItem):
    DEFAULT_CSS = """
    MacroItem Horizontal {
        width: 100%;
        height: auto;
    }
    MacroItem .macro-name {
        width: 1fr;
    }
    MacroItem .macro-name.-subordinate {
        color: $text-muted;
    }
    MacroItem .macro-options-hint {
        width: auto;
        color: $text-muted;
        text-wrap: nowrap;
    }
    """

    def __init__(self, macro: Macro) -> None:
        self.macro = macro
        # A corner arrow + indent reads as "the item above, narrowed" --
        # purely a display hint (Macro.subordinate), no behavior change.
        name = f"  ↳ {macro.name}" if macro.subordinate else macro.name
        name_classes = "macro-name -subordinate" if macro.subordinate else "macro-name"
        self._name_label = Label(name, classes=name_classes)
        hint = "options →" if macro.options else ""
        self._hint_label = Label(hint, classes="macro-options-hint")
        super().__init__(Horizontal(self._name_label, self._hint_label))


class MacroList(ListView):
    """Lets the user run one of the current panel's macros: a fixed
    command combination that answers one specific debugging question in a
    single shot, shown as a template rather than raw scrolling log lines.
    Macros that declare options show an "options →" hint; pressing → opens
    them the same way it opens a command's flags.
    """

    DEFAULT_CSS = """
    MacroList {
        height: 8;
        border: round $primary;
    }
    """

    BINDINGS = [
        Binding("right", "open_options", "Options", show=False),
    ]

    class RunMacro(Message):
        def __init__(self, macro: Macro) -> None:
            self.macro = macro
            super().__init__()

    class OpenOptions(Message):
        def __init__(self, macro: Macro) -> None:
            self.macro = macro
            super().__init__()

    def __init__(self, macros: list[Macro], **kwargs) -> None:
        super().__init__(**kwargs)
        self.macros = macros
        self.border_title = "Macros"
        self.border_subtitle = "⏎ run · → options"

    async def on_mount(self) -> None:
        for macro in self.macros:
            await self.append(MacroItem(macro))
        if self.macros:
            self.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        event.stop()
        item = event.item
        if isinstance(item, MacroItem):
            self.post_message(self.RunMacro(item.macro))

    def action_open_options(self) -> None:
        item = self.highlighted_child
        if isinstance(item, MacroItem) and item.macro.options:
            self.post_message(self.OpenOptions(item.macro))
