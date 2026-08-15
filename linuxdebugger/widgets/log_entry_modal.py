from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from ..clipboard import copy_to_clipboard


class LogEntryModal(ModalScreen[None]):
    """Shows a single log entry in full, with a copy action.

    More actions can be added here later; for now just Copy.
    """

    DEFAULT_CSS = """
    LogEntryModal {
        align: center middle;
    }
    LogEntryModal > Vertical {
        width: 80%;
        max-width: 120;
        height: auto;
        max-height: 80%;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    LogEntryModal Static#message {
        margin-top: 1;
        height: auto;
    }
    LogEntryModal Label#hint {
        margin-top: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("c", "copy", "Copy"),
        ("enter", "copy", "Copy"),
    ]

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Log entry")
            yield Static(self.text, id="message")
            yield Label("Enter/C: copy · Escape: close", id="hint")

    def action_copy(self) -> None:
        if copy_to_clipboard(self.app, self.text):
            self.notify("Copied to clipboard", title="Line copied")

    def action_close(self) -> None:
        self.dismiss(None)
