from textual import events
from textual.containers import Vertical
from textual.widgets import Static

from .log_view import LogView
from .macro_view import MacroView


class LogMacroTabs(Static):
    """Small indicator mirroring PanelTabs, showing which of Log output /
    Macro output is currently shown and the shortcut to flip between them.
    """

    DEFAULT_CSS = """
    LogMacroTabs {
        height: 1;
        content-align: center middle;
        color: $text-muted;
    }
    """

    def show(self, active: str) -> None:
        names = ["Log output", "Macro output"]
        tags = []
        for name in names:
            if name == active:
                tags.append(f"[reverse bold] {name} [/reverse bold]")
            else:
                tags.append(f"[dim] {name} [/dim]")
        self.update(f"ctrl+← {' '.join(tags)} ctrl+→")


class LogMacroPane(Vertical):
    """Houses the raw Log output and the templated Macro output in the
    same screen region, one at a time -- not split side by side. Once a
    macro has produced a result, Ctrl+Right/Ctrl+Left flip between the two
    while either has focus, the same gesture already used to switch panels
    in the Commands widget, just scoped to whichever child is focused here
    instead of to the app as a whole.
    """

    can_focus = False

    def __init__(self, log_view: LogView, macro_view: MacroView, **kwargs) -> None:
        super().__init__(**kwargs)
        self.log_view = log_view
        self.macro_view = macro_view
        self.tabs = LogMacroTabs(id="log-macro-tabs")
        self.tabs.display = False
        self._macro_available = False
        self._showing_macro = False

    def compose(self):
        yield self.tabs
        yield self.log_view
        yield self.macro_view

    def set_macro_available(self, available: bool) -> None:
        self._macro_available = available
        self.tabs.display = available
        if not available:
            self.show_log()
        else:
            self._update_tabs()

    def _update_tabs(self) -> None:
        if self._macro_available:
            self.tabs.show("Macro output" if self._showing_macro else "Log output")

    def show_log(self) -> None:
        self._showing_macro = False
        self.log_view.display = True
        self.log_view.focus()
        self.macro_view.display = False
        self._update_tabs()

    def show_macro(self) -> None:
        if not self._macro_available:
            return
        self._showing_macro = True
        self.macro_view.display = True
        self.macro_view.focus()
        self.log_view.display = False
        self._update_tabs()

    def on_key(self, event: events.Key) -> None:
        if not self._macro_available:
            return
        if event.key == "ctrl+right" and not self._showing_macro:
            self.show_macro()
            event.stop()
        elif event.key == "ctrl+left" and self._showing_macro:
            self.show_log()
            event.stop()
