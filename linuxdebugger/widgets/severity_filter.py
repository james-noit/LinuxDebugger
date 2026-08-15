from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static

from ..severity import DEFAULT_COLOR, SEVERITY_ABBR, SEVERITY_COLORS, SEVERITY_ORDER


class SeverityFilter(Static, can_focus=True):
    """Multi-select row of severity toggles for the log pane.

    Left/Right move a cursor between the 8 severities, Enter/Space toggles
    the one under the cursor on or off. No selection means "show all".
    """

    DEFAULT_CSS = """
    SeverityFilter {
        height: 3;
        border: round $primary;
        padding: 0 1;
        content-align: left middle;
    }
    SeverityFilter:focus {
        border: round $accent;
    }
    """

    BINDINGS = [
        Binding("left", "move(-1)", "Prev", show=False),
        Binding("right", "move(1)", "Next", show=False),
        Binding("enter", "toggle", "Toggle", show=False),
        Binding("space", "toggle", "Toggle", show=False),
    ]

    class Changed(Message):
        def __init__(self, severities: set[str]) -> None:
            self.severities = severities
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.border_title = "Severity"
        self._selected: set[str] = set()
        self._cursor = 0
        self._refresh_content()

    @property
    def selected(self) -> set[str]:
        return set(self._selected)

    def action_move(self, direction: int) -> None:
        self._cursor = (self._cursor + direction) % len(SEVERITY_ORDER)
        self._refresh_content()

    def action_toggle(self) -> None:
        level = SEVERITY_ORDER[self._cursor]
        if level in self._selected:
            self._selected.discard(level)
        else:
            self._selected.add(level)
        self._refresh_content()
        self.post_message(self.Changed(self.selected))

    def on_focus(self, event: events.Focus) -> None:
        self._refresh_content()

    def on_blur(self, event: events.Blur) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        line = Text()
        if not self._selected:
            # Explicit placeholder rather than leaving the row looking like
            # nothing is set at all -- this *is* the "no filter" state.
            line.append("All  ", style="bold italic")
        for index, level in enumerate(SEVERITY_ORDER):
            color = SEVERITY_COLORS.get(level, DEFAULT_COLOR)
            checked = level in self._selected
            style = f"bold {color}" if checked else f"dim {color}"
            if index == self._cursor and self.has_focus:
                style += " reverse"
            label = SEVERITY_ABBR[level]
            line.append(f" {label} " if checked else f" {label.lower()} ", style=style)
        self.update(line)
        # Always-visible shortcut hint, so the interaction is discoverable
        # without needing to already know it.
        self.border_subtitle = "←→ move · ⏎ toggle"
