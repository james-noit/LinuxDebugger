from datetime import datetime, timedelta

from rich.text import Text
from textual import events
from textual.selection import Selection
from textual.widgets import RichLog

from ..clipboard import copy_to_clipboard
from ..severity import LogEntry

MAX_LINES = 20_000


class LogView(RichLog):
    """Read-only, scrollable log area. Selecting text copies it to the
    clipboard automatically, and lines can be filtered by severity and/or
    time range without losing what's been captured.

    RichLog doesn't implement text-selection extraction itself — its
    inherited `get_selection` assumes a single Text/Content renders the
    whole widget, which isn't true for a line-oriented log — so every
    *visible* (post-filter) line is mirrored as plain text here and
    extraction/copy is implemented against that mirror. Wrapping is kept
    off so that one logical line always maps to exactly one rendered row,
    which is what keeps that mirror's indices in sync with RichLog's own.

    All appended lines are also kept in `_all_entries` regardless of the
    active filters, so changing a filter re-renders from that instead of
    permanently discarding anything that's already been captured.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(
            max_lines=MAX_LINES,
            wrap=False,
            markup=False,
            auto_scroll=True,
            **kwargs,
        )
        self.border_title = "Log output"
        self._all_entries: list[LogEntry] = []
        self._visible_plain: list[str] = []
        self._severities: set[str] = set()
        self._time_range: timedelta | None = None

    def append_text(self, text: str) -> None:
        if not text:
            return
        for line in text.splitlines():
            self._add_entry(LogEntry(styled=Text(line), plain=line))

    def append_entry(self, entry: LogEntry) -> None:
        self._add_entry(entry)

    def set_filters(self, severities: set[str], time_range: timedelta | None) -> None:
        if severities == self._severities and time_range == self._time_range:
            return
        self._severities = severities
        self._time_range = time_range
        self._render_visible()

    def _since(self) -> datetime | None:
        # Computed fresh on every check (rather than storing a fixed
        # cutoff) so a range like "last 5 min" keeps sliding forward as
        # real time passes, both for already-buffered entries and for new
        # ones arriving during a `-f`/`-w` follow session.
        if self._time_range is None:
            return None
        return datetime.now() - self._time_range

    def _add_entry(self, entry: LogEntry) -> None:
        self._all_entries.append(entry)
        overflow = len(self._all_entries) - MAX_LINES
        if overflow > 0:
            del self._all_entries[:overflow]

        if not entry.matches(self._severities, self._since()):
            return

        at_bottom = self.is_vertical_scroll_end
        self.write(entry.styled, scroll_end=at_bottom)
        self._visible_plain.append(entry.plain)
        overflow = len(self._visible_plain) - MAX_LINES
        if overflow > 0:
            del self._visible_plain[:overflow]

    def _render_visible(self) -> None:
        self.clear()
        self._visible_plain.clear()
        since = self._since()
        for entry in self._all_entries:
            if entry.matches(self._severities, since):
                self.write(entry.styled, scroll_end=False)
                self._visible_plain.append(entry.plain)
        self.scroll_end(animate=False)

    @property
    def is_filtered(self) -> bool:
        return bool(self._severities) or self._time_range is not None

    @property
    def visible_plain(self) -> list[str]:
        return list(self._visible_plain)

    @property
    def all_plain(self) -> list[str]:
        return [entry.plain for entry in self._all_entries]

    def on_click(self, event: events.Click) -> None:
        # A plain click (no drag) never reaches selection_updated -- Textual
        # only calls that for an actual mouse-drag selection -- so this is
        # the single-line-click path exclusively; the two never double-fire
        # for the same interaction.
        index = event.y + int(self.scroll_offset.y)
        if not (0 <= index < len(self._visible_plain)):
            return
        text = self._visible_plain[index]
        if not text or not copy_to_clipboard(self.app, text):
            return
        preview = text if len(text) <= 60 else text[:57] + "..."
        self.notify(f"Copied: {preview}", title="Line copied")

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        if not self._visible_plain:
            return None
        text = "\n".join(self._visible_plain)
        return selection.extract(text), "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        super().selection_updated(selection)
        if selection is None:
            return
        result = self.get_selection(selection)
        if result is None:
            return
        text, _ = result
        if text:
            copy_to_clipboard(self.app, text)

    def clear_log(self) -> None:
        self.clear()
        self._all_entries.clear()
        self._visible_plain.clear()
