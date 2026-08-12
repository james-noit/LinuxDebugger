from textual.containers import VerticalScroll
from textual.widgets import Static

from ..commands import Flag


class FlagDescription(VerticalScroll):
    """Small box showing the description of the flag currently in focus."""

    DEFAULT_CSS = """
    FlagDescription {
        height: 8;
        border: round $warning;
        padding: 0 1;
    }
    FlagDescription > Static {
        height: auto;
        color: $foreground;
    }
    """

    can_focus = False

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Flag"

    def compose(self):
        yield Static("", id="body")

    def show(self, flag: Flag | None) -> None:
        body = self.query_one("#body", Static)
        if flag is None:
            body.update("")
            return
        body.update(f"{flag.label}\n\n{flag.description}")
        self.scroll_home(animate=False)
