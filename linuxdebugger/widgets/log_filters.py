from textual.app import ComposeResult
from textual.containers import Horizontal

from .severity_filter import SeverityFilter
from .time_range_filter import TimeRangeFilter


class LogFilters(Horizontal):
    """Container for the severity and time-range filter controls."""

    DEFAULT_CSS = """
    LogFilters {
        height: 3;
    }
    LogFilters SeverityFilter {
        width: 2fr;
    }
    LogFilters TimeRangeFilter {
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield SeverityFilter(id="severity-filter")
        yield TimeRangeFilter(id="time-range-filter")
