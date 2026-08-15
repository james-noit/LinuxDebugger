from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static


class ExportModal(ModalScreen[tuple[str, str] | None]):
    """Asks whether to export the filtered (visible) or full log, and where."""

    DEFAULT_CSS = """
    ExportModal {
        align: center middle;
    }
    ExportModal > Vertical {
        width: 64;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    ExportModal Static#scope {
        margin-top: 1;
        text-style: bold;
    }
    ExportModal Static#error {
        color: $error;
    }
    ExportModal Input {
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        # Not left/right: Input (focused by default, for the path field)
        # consumes those itself for text-cursor movement, so they'd never
        # reach this binding.
        ("ctrl+t", "toggle_scope", "Toggle scope"),
    ]

    def __init__(self, has_filter: bool, default_path: str) -> None:
        super().__init__()
        self.has_filter = has_filter
        self.scope = "filtered" if has_filter else "all"
        self.default_path = default_path

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Export log")
            yield Static(id="scope")
            if not self.has_filter:
                yield Label(
                    "(no filter is currently applied, so both scopes are "
                    "the same)"
                )
            yield Static("", id="error")
            yield Input(value=self.default_path, id="path-input")

    def on_mount(self) -> None:
        self._update_scope()
        self.query_one(Input).focus()

    def action_toggle_scope(self) -> None:
        self.scope = "all" if self.scope == "filtered" else "filtered"
        self._update_scope()

    def _update_scope(self) -> None:
        label = (
            "Filtered — only what's currently visible"
            if self.scope == "filtered"
            else "All — everything captured, ignoring filters"
        )
        self.query_one("#scope", Static).update(f"Scope (Ctrl+T to change): {label}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        path = event.value.strip()
        if not path:
            self.query_one("#error", Static).update("Enter a file path")
            return
        self.dismiss((self.scope, path))

    def action_cancel(self) -> None:
        self.dismiss(None)
