from datetime import datetime, timedelta
from typing import Callable

from rich.text import Text
from textual import events
from textual.message import Message
from textual.selection import Selection
from textual.widgets import RichLog

from ..clipboard import copy_to_clipboard
from ..severity import LogEntry

MAX_LINES = 20_000


class LogView(RichLog):
    """Read-only, scrollable log area.

    - Drag-selecting text copies it to the clipboard automatically.
    - A plain click on a single line copies just that line and notifies.
    - Lines can be filtered by severity, time range, and/or a typed search
      (type while focused), without losing what's been captured.
    - Up/Down move a selection cursor between visible entries; Enter opens
      the selected entry in detail (with its own copy action).

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

    def __init__(
        self,
        on_search_changed: Callable[[str, int], None] | None = None,
        **kwargs,
    ) -> None:
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
        self._search_text: str = ""
        self._cursor_index: int | None = None
        self._pending_click_index: int | None = None
        self._suspend_auto_scroll = False
        self._was_at_bottom = False
        self._on_search_changed = on_search_changed

    class OpenEntry(Message):
        def __init__(self, text: str) -> None:
            self.text = text
            super().__init__()

    # -- appending ----------------------------------------------------

    def append_text(self, text: str) -> None:
        if not text:
            return
        for line in text.splitlines():
            self._add_entry(LogEntry(styled=Text(line), plain=line))

    def append_entry(self, entry: LogEntry) -> None:
        self._add_entry(entry)

    # -- filtering / search --------------------------------------------

    def set_filters(self, severities: set[str], time_range: timedelta | None) -> None:
        if severities == self._severities and time_range == self._time_range:
            return
        self._severities = severities
        self._time_range = time_range
        self._cursor_index = None
        self._render_visible()

    def set_search(self, text: str) -> None:
        if text == self._search_text:
            return
        self._search_text = text
        self._cursor_index = None
        self._render_visible()

    def _since(self) -> datetime | None:
        # Computed fresh on every check (rather than storing a fixed
        # cutoff) so a range like "last 5 min" keeps sliding forward as
        # real time passes, both for already-buffered entries and for new
        # ones arriving during a `-f`/`-w` follow session.
        if self._time_range is None:
            return None
        return datetime.now() - self._time_range

    def _passes(self, entry: LogEntry, since: datetime | None) -> bool:
        if not entry.matches(self._severities, since):
            return False
        if self._search_text and self._search_text.lower() not in entry.plain.lower():
            return False
        return True

    def _add_entry(self, entry: LogEntry) -> None:
        self._all_entries.append(entry)
        overflow = len(self._all_entries) - MAX_LINES
        if overflow > 0:
            del self._all_entries[:overflow]

        if not self._passes(entry, self._since()):
            return

        at_bottom = self.is_vertical_scroll_end and not self._suspend_auto_scroll
        self.write(entry.styled, scroll_end=at_bottom)
        self._visible_plain.append(entry.plain)
        overflow = len(self._visible_plain) - MAX_LINES
        if overflow > 0:
            del self._visible_plain[:overflow]
        self._notify_search_changed()

    def _render_visible(self) -> None:
        self.clear()
        self._visible_plain.clear()
        since = self._since()
        visible_index = 0
        for entry in self._all_entries:
            if self._passes(entry, since):
                is_cursor = visible_index == self._cursor_index
                # A background/reverse style alone isn't reliable here --
                # confirmed against real terminal output that Textual's
                # RichLog doesn't consistently paint a per-segment style
                # override on top of the widget's own background, even
                # though the Strip itself carries the right Style object
                # right up to the render_line() call. A text marker is
                # guaranteed visible since it's real content, not styling.
                marker = Text("▶ ", style="bold bright_yellow") if is_cursor else Text("  ")
                content = marker + entry.styled
                if is_cursor:
                    content.stylize("bold black on bright_yellow")
                self.write(content, scroll_end=False)
                self._visible_plain.append(entry.plain)
                visible_index += 1
        if self._cursor_index is None:
            self.scroll_end(animate=False)
        self._notify_search_changed()

    def _notify_search_changed(self) -> None:
        if self._on_search_changed is not None:
            self._on_search_changed(self._search_text, len(self._visible_plain))

    @property
    def is_filtered(self) -> bool:
        return (
            bool(self._severities)
            or self._time_range is not None
            or bool(self._search_text)
        )

    @property
    def visible_plain(self) -> list[str]:
        return list(self._visible_plain)

    @property
    def all_plain(self) -> list[str]:
        return [entry.plain for entry in self._all_entries]

    # -- keyboard cursor navigation ------------------------------------

    def on_key(self, event: events.Key) -> None:
        if event.key == "up":
            self._move_cursor(-1)
            event.stop()
        elif event.key == "down":
            self._move_cursor(1)
            event.stop()
        elif event.key == "enter":
            if self._cursor_index is not None and 0 <= self._cursor_index < len(
                self._visible_plain
            ):
                self.post_message(self.OpenEntry(self._visible_plain[self._cursor_index]))
            event.stop()
        elif event.key == "backspace":
            if self._search_text:
                self.set_search(self._search_text[:-1])
            event.stop()
        elif event.key == "escape":
            if self._search_text:
                self.set_search("")
                event.stop()
            elif self._cursor_index is not None:
                self._cursor_index = None
                self._render_visible()
                event.stop()
        elif event.is_printable and event.character:
            self.set_search(self._search_text + event.character)
            event.stop()

    def _move_cursor(self, direction: int) -> None:
        if not self._visible_plain:
            return
        if self._cursor_index is None:
            self._cursor_index = 0 if direction > 0 else len(self._visible_plain) - 1
        else:
            self._cursor_index = max(
                0, min(len(self._visible_plain) - 1, self._cursor_index + direction)
            )
        self._render_visible()
        self._ensure_cursor_visible()

    def _ensure_cursor_visible(self) -> None:
        if self._cursor_index is None:
            return
        top = int(self.scroll_offset.y)
        height = self.scrollable_content_region.height or self.size.height
        if self._cursor_index < top:
            self.scroll_to(y=self._cursor_index, animate=False)
        elif self._cursor_index >= top + height:
            self.scroll_to(y=self._cursor_index - height + 1, animate=False)

    # -- mouse: click-to-copy / drag-to-select --------------------------

    def on_mouse_down(self, event: events.MouseDown) -> None:
        # Resolve which line this targets as early as possible (mouse-down
        # rather than waiting for Click) *and* freeze auto-scroll until the
        # button comes back up. Without this, new lines arriving between
        # down and up during a live `-f`/`-w` stream can auto-scroll the
        # content, shifting what's at that row out from under the click and
        # copying the wrong (later) line -- freezing means the row the user
        # is looking at physically cannot move during the interaction.
        self._was_at_bottom = self.is_vertical_scroll_end
        self._suspend_auto_scroll = True
        # event.y is relative to the widget's *outer* region (border
        # included), not its content area, so the top border/padding has
        # to be subtracted -- confirmed against real terminal mouse input
        # (Pilot's synthetic clicks in tests use content-relative
        # coordinates directly and don't exhibit this, which is why this
        # was missed before: it only shows up with real mouse clicks).
        index = event.y - self.gutter.top + int(self.scroll_offset.y)
        self._pending_click_index = index if 0 <= index < len(self._visible_plain) else None

    def on_mouse_up(self, event: events.MouseUp) -> None:
        self._suspend_auto_scroll = False
        # If the user was following live output (pinned to the bottom)
        # before this interaction, catch back up now that it's safe to --
        # any lines that arrived while frozen were appended but not scrolled
        # into view.
        if self._was_at_bottom:
            self.scroll_end(animate=False)

    def on_click(self, event: events.Click) -> None:
        # A plain click (no drag) never reaches selection_updated -- Textual
        # only calls that for an actual mouse-drag selection -- so this is
        # the single-line-click path exclusively; the two never double-fire
        # for the same interaction.
        index, self._pending_click_index = self._pending_click_index, None
        if index is None:
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
        self._cursor_index = None
        self._notify_search_changed()
