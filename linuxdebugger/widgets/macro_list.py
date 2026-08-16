from textual.message import Message
from textual.widgets import Label, ListItem, ListView

from ..macros import Macro


class MacroItem(ListItem):
    def __init__(self, macro: Macro) -> None:
        self.macro = macro
        super().__init__(Label(macro.name))


class MacroList(ListView):
    """Lets the user run one of the current panel's macros: a fixed
    command combination that answers one specific debugging question in a
    single shot, shown as a template rather than raw scrolling log lines.
    """

    DEFAULT_CSS = """
    MacroList {
        height: 8;
        border: round $primary;
    }
    """

    class RunMacro(Message):
        def __init__(self, macro: Macro) -> None:
            self.macro = macro
            super().__init__()

    def __init__(self, macros: list[Macro], **kwargs) -> None:
        super().__init__(**kwargs)
        self.macros = macros
        self.border_title = "Macros"
        self.border_subtitle = "⏎ run"

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
