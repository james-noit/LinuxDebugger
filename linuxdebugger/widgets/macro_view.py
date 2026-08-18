from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..macros import MacroResult, StatusItem

LEVEL_COLORS = {
    "ok": "green",
    "warn": "yellow",
    "crit": "red",
    "unknown": "grey62",
    "neutral": "bright_white",
}

# A plain circle glyph styled per-level, the same approach as the log
# pane's severity dot (see severity.py's DOT/_dot) -- not a colored-circle
# emoji (🟢🟡🔴⚪), which needs an emoji font to render as a color at all
# and is double-width in many terminals, throwing off alignment wherever
# one wasn't available (bare tty, minimal SSH sessions, some tmux/screen
# configs).
_DOT = "●"

_LADDER_ICONS = {
    "ok": "✔",
    "warn": "⚠",
    "crit": "✘",
    "unknown": "○",
    "neutral": "○",
}

_GAUGE_WIDTH = 22


def _title(text: Text, title: str) -> None:
    text.append(title + "\n", style="bold")
    text.append("=" * len(title) + "\n\n")


def _section_header(text: Text, name: str, *, first: bool) -> None:
    if not first:
        text.append("\n")
    text.append(name + "\n", style="bold")
    text.append("-" * len(name) + "\n\n")


def _render_fields(title: str, items: list[StatusItem]) -> Text:
    text = Text()
    _title(text, title)
    label_width = max((len(item.label) for item in items), default=0)
    current_section: str | None = None
    first_section = True
    for item in items:
        if item.section is not None and item.section != current_section:
            _section_header(text, item.section, first=first_section)
            current_section = item.section
            first_section = False
        text.append(f"{item.label.ljust(label_width)} : {item.value}\n")
    return text


def _render_semaphore(title: str, items: list[StatusItem]) -> Text:
    text = Text()
    _title(text, title)
    label_width = max((len(item.label) for item in items), default=0)
    current_section: str | None = None
    first_section = True
    for item in items:
        if item.section is not None and item.section != current_section:
            _section_header(text, item.section, first=first_section)
            current_section = item.section
            first_section = False
        color = LEVEL_COLORS.get(item.level, "bright_white")
        text.append(f"{_DOT} ", style=color)
        text.append(f"{item.label.ljust(label_width)}", style=f"bold {color}")
        text.append(f"   {item.value}\n")
    return text


def _render_ladder(title: str, items: list[StatusItem]) -> Text:
    text = Text()
    _title(text, title)
    current_section: str | None = None
    first_section = True
    for index, item in enumerate(items):
        if item.section is not None and item.section != current_section:
            _section_header(text, item.section, first=first_section)
            current_section = item.section
            first_section = False
        color = LEVEL_COLORS.get(item.level, "bright_white")
        icon = _LADDER_ICONS.get(item.level, "○")
        text.append(f"{icon} ", style=f"bold {color}")
        text.append(f"{item.label}\n", style=f"bold {color}")
        text.append(f"    {item.value}\n", style="grey62" if item.level == "unknown" else None)
        same_section_next = index < len(items) - 1 and items[index + 1].section == item.section
        if index < len(items) - 1 and (item.section is None or same_section_next):
            text.append("    │\n", style="grey42")
    return text


def _render_gauge(title: str, items: list[StatusItem]) -> Text:
    text = Text()
    _title(text, title)
    label_width = max((len(item.label) for item in items), default=0)
    current_section: str | None = None
    first_section = True
    for item in items:
        if item.section is not None and item.section != current_section:
            _section_header(text, item.section, first=first_section)
            current_section = item.section
            first_section = False
        color = LEVEL_COLORS.get(item.level, "bright_white")
        if item.percent is not None:
            pct = max(0.0, min(100.0, item.percent))
            filled = round(_GAUGE_WIDTH * pct / 100)
            text.append(f"{item.label.ljust(label_width)} ")
            text.append("█" * filled, style=color)
            text.append("░" * (_GAUGE_WIDTH - filled), style="grey42")
            text.append(f" {pct:5.1f}%  {item.value}\n")
        else:
            text.append(f"{_DOT} ", style=color)
            text.append(f"{item.label.ljust(label_width)}", style=f"bold {color}")
            text.append(f"   {item.value}\n")
    return text


_RENDERERS = {
    "fields": _render_fields,
    "semaphore": _render_semaphore,
    "ladder": _render_ladder,
    "gauge": _render_gauge,
}


class MacroView(VerticalScroll):
    """Displays a macro's result as a fixed template.

    Unlike LogView, which appends scrolling lines forever, this always
    shows one snapshot of a fixed set of items -- the shape a future
    live-updating monitor will reuse, re-rendering the same template with
    fresh values on each tick instead of a one-time snapshot.

    `MacroResult.kind` picks which of four renderers formats the items:
    a plain label/value list, a semaphore (traffic-light) panel, a
    pass/fail ladder, or a percentage gauge -- each macro picks whichever
    best communicates its particular result.
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

    def show(self, result: MacroResult) -> None:
        renderer = _RENDERERS.get(result.kind, _render_fields)
        self.query_one("#body", Static).update(renderer(result.title, result.items))
