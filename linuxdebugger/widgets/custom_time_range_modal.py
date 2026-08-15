import re
from datetime import timedelta

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

_UNITS = {
    "s": ("seconds", "s"),
    "m": ("minutes", "min"),
    "h": ("hours", "h"),
    "d": ("days", "d"),
}
_INPUT_RE = re.compile(r"^\s*(\d+)\s*([smhd]?)\s*$", re.IGNORECASE)


def parse_custom_range(value: str) -> tuple[timedelta, str] | None:
    """Parse e.g. '45', '45m', '2h', '3d' into (timedelta, display label)."""
    match = _INPUT_RE.match(value)
    if not match:
        return None
    amount = int(match.group(1))
    if amount <= 0:
        return None
    unit = (match.group(2) or "m").lower()
    kwarg, suffix = _UNITS[unit]
    return timedelta(**{kwarg: amount}), f"Last {amount}{suffix}"


class CustomTimeRangeModal(ModalScreen[tuple[timedelta, str] | None]):
    """Asks for a custom "look back" duration, e.g. '45m', '2h', '3d'."""

    DEFAULT_CSS = """
    CustomTimeRangeModal {
        align: center middle;
    }
    CustomTimeRangeModal > Vertical {
        width: 50;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    CustomTimeRangeModal Static#error {
        color: $error;
        height: auto;
    }
    CustomTimeRangeModal Input {
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("Custom time range")
            yield Label("How far back? e.g. 45m, 2h, 3d (plain number = minutes)")
            yield Static("", id="error")
            yield Input(placeholder="45m", id="range-input")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        parsed = parse_custom_range(event.value)
        if parsed is None:
            self.query_one("#error", Static).update(
                "Enter a number, e.g. 45m, 2h or 3d"
            )
            return
        self.dismiss(parsed)

    def action_cancel(self) -> None:
        self.dismiss(None)
