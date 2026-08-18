from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static
from textual.widgets._header import HeaderIcon, HeaderTitle
from textual.widgets import Header as _Header

from ..version import get_version
from .panel_tabs import PanelTabs


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
    """Header with a version label instead of the clock space, plus a
    second row for the panel tab strip.

    The tab strip used to live in the left pane, but that pane is a fixed
    42 columns wide -- comfortable for two or three short panel names, but
    it started visibly overflowing once a fourth, longer name (System
    Check) joined. The header spans the full terminal width instead, so
    the strip has room to grow with the app rather than fighting a fixed
    budget.
    """

    DEFAULT_CSS = """
    Header {
        height: 2;
    }
    Header > #header-top-row {
        height: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(id="header-top-row"):
            yield HeaderIcon().data_bind(_Header.icon)
            yield HeaderTitle()
            yield HeaderVersion()
        yield PanelTabs(id="panel-tabs")
