from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static


class PasswordModal(ModalScreen[str | None]):
    """Asks for the sudo password (masked) before running a privileged
    command or macro step. `subject_label`/`subject_text` name whatever is
    about to be elevated (a resolved command line, a macro's name...) --
    this modal doesn't otherwise care what kind of thing that is."""

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

    def __init__(
        self,
        subject_text: str,
        subject_label: str = "Command",
        error: str | None = None,
    ) -> None:
        super().__init__()
        self.subject_text = subject_text
        self.subject_label = subject_label
        self.error = error

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("⚠ This requires sudo access", id="title")
            yield Label(f"{self.subject_label}: {self.subject_text}")
            if self.error:
                yield Static(self.error, id="error")
            yield Input(placeholder="sudo password", password=True, id="password")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)
