from textual.widgets import Static


class FilterBar(Static):
    """Shows the text currently typed to filter the command list."""

    DEFAULT_CSS = """
    FilterBar {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    FilterBar.-active {
        color: $text;
        text-style: bold;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.show("")

    def show(self, filter_text: str) -> None:
        if filter_text:
            self.update(f"🔎 {filter_text}▏")
        else:
            self.update("🔎 type to filter…")
        self.set_class(bool(filter_text), "-active")
