from textual.widgets import Static


class LogSearchBar(Static):
    """Shows the text currently typed to search the log, and match count."""

    DEFAULT_CSS = """
    LogSearchBar {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    LogSearchBar.-active {
        color: $text;
        text-style: bold;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.show("", 0)

    def show(self, text: str, count: int) -> None:
        if not text:
            self.update("🔎 click the log and type to search…")
        else:
            plural = "" if count == 1 else "es"
            self.update(f"🔎 {text}▏  ({count} match{plural})")
        self.set_class(bool(text), "-active")
