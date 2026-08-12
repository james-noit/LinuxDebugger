from textual.widgets import TextArea

from ..clipboard import copy_to_clipboard

MAX_LINES = 20_000


class LogView(TextArea):
    """Read-only, scrollable log area. Selecting text copies it to the
    clipboard automatically."""

    def __init__(self, **kwargs) -> None:
        super().__init__(
            "",
            read_only=True,
            show_line_numbers=False,
            soft_wrap=True,
            **kwargs,
        )
        self.border_title = "Log output"

    def on_text_area_selection_changed(self, event: TextArea.SelectionChanged) -> None:
        text = self.selected_text
        if text:
            copy_to_clipboard(self.app, text)

    def append_text(self, text: str) -> None:
        if not text:
            return
        at_bottom = self.is_vertical_scroll_end
        self.insert(text, location=self.document.end)
        self._trim()
        if at_bottom:
            self.move_cursor(self.document.end)
            self.scroll_end(animate=False)

    def _trim(self) -> None:
        line_count = self.document.line_count
        if line_count > MAX_LINES:
            overflow = line_count - MAX_LINES
            self.replace("", (0, 0), (overflow, 0), maintain_selection_offset=False)

    def clear_log(self) -> None:
        self.load_text("")
