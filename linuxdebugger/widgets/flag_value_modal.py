from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, ListItem, ListView

from ..commands import Flag


class FlagValueModal(ModalScreen[str | None]):
    """Lets the user pick a value for a customizable flag.

    Proposed values are just a starting point (`Flag.proposed_values`, which
    can grow over time without touching this widget) -- typing anything else
    into the input and pressing Enter always works too.
    """

    DEFAULT_CSS = """
    FlagValueModal {
        align: center middle;
    }
    FlagValueModal > Vertical {
        width: 56;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    FlagValueModal Label#hint {
        color: $text-muted;
    }
    FlagValueModal ListView {
        height: auto;
        max-height: 10;
        margin-top: 1;
        border: round $primary-lighten-1;
    }
    FlagValueModal Input {
        margin-top: 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, flag: Flag, current_value: str) -> None:
        super().__init__()
        self.flag = flag
        self.current_value = current_value

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(f"Customize: {self.flag.label}")
            yield Label(
                "Pick a value below, or type your own and press Enter.", id="hint"
            )
            if self.flag.proposed_values:
                with ListView(id="proposed"):
                    for value in self.flag.proposed_values:
                        yield ListItem(Label(value), name=value)
            yield Input(value=self.current_value, id="value-input")

    def on_mount(self) -> None:
        proposed = self.flag.proposed_values
        value_input = self.query_one("#value-input", Input)
        if proposed:
            value_input.border_subtitle = "⇥ tab to select"
            list_view = self.query_one("#proposed", ListView)
            list_view.border_subtitle = "⇥ tab for custom value"
            if self.current_value in proposed:
                list_view.index = proposed.index(self.current_value)
            list_view.focus()
        else:
            value_input.focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is not None and event.item.name:
            self.dismiss(event.item.name)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if value:
            self.dismiss(value)

    def action_cancel(self) -> None:
        self.dismiss(None)
