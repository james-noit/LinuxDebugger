from textual.app import ComposeResult
from textual.widgets import Static
from textual.widgets._header import HeaderIcon, HeaderTitle
from textual.widgets import Header as _Header

from ..version import get_version


class HeaderVersion(Static):
    """Displays the app version docked to the top right of the header."""

    DEFAULT_CSS = """
    HeaderVersion {
        dock: right;
        width: auto;
        padding: 0 2;
        content-align: center middle;
        color: $foreground;
        text-opacity: 85%;
    }
    """

    def render(self) -> str:
        return f"v{get_version()}"


class Header(_Header):
    """Header with a version label instead of the clock space on the right."""

    def compose(self) -> ComposeResult:
        yield HeaderIcon().data_bind(_Header.icon)
        yield HeaderTitle()
        yield HeaderVersion()
