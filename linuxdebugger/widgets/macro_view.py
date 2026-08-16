from textual.containers import VerticalScroll
from textual.widgets import Static


class MacroView(VerticalScroll):
    """Displays a macro's result as a fixed label/value template.

    Unlike LogView, which appends scrolling lines forever, this always
    shows one snapshot of a fixed set of fields -- the shape a future
    live-updating monitor will reuse, re-rendering the same template with
    fresh values on each tick instead of a one-time snapshot.
    """

    DEFAULT_CSS = """
    MacroView {
        padding: 0 1;
    }
    """

    can_focus = True

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Macro output"

    def compose(self):
        yield Static("", id="body")

    def show_message(self, text: str) -> None:
        self.query_one("#body", Static).update(text)

    def show(self, title: str, fields: list[tuple[str, str]]) -> None:
        label_width = max((len(label) for label, _ in fields), default=0)
        lines = [title, "=" * len(title), ""]
        for label, value in fields:
            lines.append(f"{label.ljust(label_width)} : {value}")
        self.query_one("#body", Static).update("\n".join(lines))
