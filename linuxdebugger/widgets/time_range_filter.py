from datetime import timedelta

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static

PRESETS: list[tuple[str, timedelta | None]] = [
    ("All time", None),
    ("Last 5 min", timedelta(minutes=5)),
    ("Last 15 min", timedelta(minutes=15)),
    ("Last hour", timedelta(hours=1)),
    ("Last 24 hours", timedelta(hours=24)),
    ("Last 7 days", timedelta(days=7)),
]


class TimeRangeFilter(Static, can_focus=True):
    """Cyclable time-range picker for the log pane, plus a custom range.

    Left/Right cycle through the presets (applied immediately, like a
    live preview). Enter always opens a prompt for a custom range,
    regardless of where the cycle currently sits.
    """

    DEFAULT_CSS = """
    TimeRangeFilter {
        height: 3;
        border: round $primary;
        padding: 0 1;
        content-align: left middle;
    }
    TimeRangeFilter:focus {
        border: round $accent;
    }
    """

    BINDINGS = [
        Binding("left", "cycle(-1)", "Prev", show=False),
        Binding("right", "cycle(1)", "Next", show=False),
        Binding("enter", "custom", "Custom", show=False),
    ]

    class Changed(Message):
        def __init__(self, time_range: timedelta | None) -> None:
            self.time_range = time_range
            super().__init__()

    class OpenCustom(Message):
        pass

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.border_title = "Time range"
        self._preset_index = 0
        self._custom: timedelta | None = None
        self._custom_label = ""
        self._refresh_content()

    @property
    def current(self) -> timedelta | None:
        return self._custom if self._custom is not None else PRESETS[self._preset_index][1]

    def action_cycle(self, direction: int) -> None:
        self._custom = None
        self._preset_index = (self._preset_index + direction) % len(PRESETS)
        self._refresh_content()
        self.post_message(self.Changed(self.current))

    def action_custom(self) -> None:
        self.post_message(self.OpenCustom())

    def set_custom(self, delta: timedelta, label: str) -> None:
        self._custom = delta
        self._custom_label = label
        self._refresh_content()
        self.post_message(self.Changed(self.current))

    def _refresh_content(self) -> None:
        label = self._custom_label if self._custom is not None else PRESETS[self._preset_index][0]
        self.update(Text(label, style="bold"))
        self.border_subtitle = "←→ presets · ⏎ custom"
