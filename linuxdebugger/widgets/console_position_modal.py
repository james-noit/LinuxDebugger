from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label


class ConsolePositionModal(ModalScreen[str | None]):
    """Asks where the console should live, the first time it's opened.
    The answer is persisted (see settings.py) so this only appears once --
    afterwards the choice can still be changed from the command palette
    (Ctrl+P), which is what this modal itself points at rather than
    duplicating a settings UI here."""

    DEFAULT_CSS = """
    ConsolePositionModal {
        align: center middle;
    }
    ConsolePositionModal > Vertical {
        width: 56;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    ConsolePositionModal Label#title {
        text-style: bold;
    }
    ConsolePositionModal Label#hint {
        color: $text-muted;
        margin-top: 1;
    }
    ConsolePositionModal Horizontal {
        height: auto;
        margin-top: 1;
        align: center middle;
    }
    ConsolePositionModal Button {
        margin: 0 1;
        min-width: 12;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Where should the console open?", id="title")
            yield Label(
                "You can change this later from the command palette (Ctrl+P).",
                id="hint",
            )
            with Horizontal():
                yield Button("Bottom", id="bottom", variant="primary")
                yield Button("Right", id="right", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)

    def action_cancel(self) -> None:
        self.dismiss(None)
