from textual.containers import VerticalScroll
from textual.widgets import Static

from ..commands import Command


class CommandDescription(VerticalScroll):
    """Box under the command list explaining the highlighted command and,
    once flags have been picked, previewing the resulting full command."""

    DEFAULT_CSS = """
    CommandDescription {
        height: 12;
        border: round $primary;
        padding: 0 1;
    }
    CommandDescription > Static {
        height: auto;
        color: $foreground;
    }
    """

    can_focus = False

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.border_title = "Description"

    def compose(self):
        yield Static("", id="body")

    def show(
        self,
        command: Command | None,
        selected_flags: set[int] | None = None,
        values: dict[int, str] | None = None,
    ) -> None:
        body = self.query_one("#body", Static)

        if command is None:
            body.update("")
            return

        selected_flags = selected_flags or set()
        values = values or {}
        tokens = [command.name, *command.base_args]
        for index in sorted(selected_flags):
            tokens.extend(command.flags[index].resolved_tokens(values.get(index)))
        preview = " ".join(tokens)
        sudo_note = "  (requires sudo)" if command.requires_sudo else ""

        lines = [f"$ {preview}{sudo_note}", "", command.description]

        if selected_flags:
            lines.append("")
            lines.append("Flags applied:")
            for index in sorted(selected_flags):
                flag = command.flags[index]
                label = flag.resolved_label(values.get(index))
                lines.append(f" • {label} — {flag.description}")

        body.update("\n".join(lines))
        self.scroll_home(animate=False)
