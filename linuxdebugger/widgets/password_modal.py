from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from ..commands import Command


class PasswordModal(ModalScreen[str | None]):
    """Asks for the sudo password (masked) before running a privileged command."""

    DEFAULT_CSS = """
    PasswordModal {
        align: center middle;
    }
    PasswordModal > Vertical {
        width: 60;
        height: auto;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }
    PasswordModal Label#title {
        color: $warning;
        text-style: bold;
    }
    PasswordModal Static#error {
        color: $error;
    }
    PasswordModal Input {
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, command: Command, error: str | None = None) -> None:
        super().__init__()
        self.command = command
        self.error = error

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("⚠ This command requires sudo access", id="title")
            yield Label(f"Command: {self.command.name}")
            if self.error:
                yield Static(self.error, id="error")
            yield Input(placeholder="sudo password", password=True, id="password")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)
