from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from ..macros import Macro


class MacroConfirmModal(ModalScreen[bool]):
    """Confirms exactly which commands a macro is about to run before it
    runs them -- macros are otherwise opaque compared to a regular
    command, whose full argv is always visible before you press Enter."""

    DEFAULT_CSS = """
    MacroConfirmModal {
        align: center middle;
    }
    MacroConfirmModal > Vertical {
        width: 70;
        height: auto;
        border: round $warning;
        background: $surface;
        padding: 1 2;
    }
    MacroConfirmModal Label#title {
        color: $warning;
        text-style: bold;
    }
    MacroConfirmModal Static#steps {
        margin-top: 1;
        color: $success;
    }
    MacroConfirmModal Label#hint {
        margin-top: 1;
        color: $text-muted;
    }
    """

    BINDINGS = [
        ("enter", "confirm", "Run"),
        ("escape", "cancel", "Cancel"),
    ]

    def __init__(self, macro: Macro) -> None:
        super().__init__()
        self.macro = macro

    def compose(self) -> ComposeResult:
        steps_text = "\n".join(f"$ {' '.join(step)}" for step in self.macro.steps)
        with Vertical():
            yield Label(f"Run macro: {self.macro.name}", id="title")
            yield Static(self.macro.description)
            yield Static(steps_text or "(no external commands)", id="steps")
            yield Label("⏎ run this macro   ·   Escape cancel", id="hint")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
