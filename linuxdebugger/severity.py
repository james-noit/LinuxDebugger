"""Maps journalctl/dmesg severity info to a colored hollow-circle indicator,
and parses out the severity + timestamp of each line so the log pane can
filter by them.

Both journalctl (via `--output=json`) and dmesg (via `-x -T`, decoded with a
human/wall-clock timestamp) expose the syslog severity and a timestamp per
line.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime

from rich.text import Text

DOT = "○"

# Most severe first -- this order is also the filtering threshold order:
# "show <level> and above" means "at or before <level>'s index".
SEVERITY_ORDER = ["emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"]

SEVERITY_COLORS: dict[str, str] = {
    "emerg": "bright_red",
    "alert": "bright_red",
    "crit": "bright_red",
    "err": "red",
    "warning": "yellow",
    "notice": "cyan",
    "info": "green",
    "debug": "grey62",
}
DEFAULT_COLOR = "grey62"

SEVERITY_ABBR: dict[str, str] = {
    "emerg": "EMG",
    "alert": "ALR",
    "crit": "CRT",
    "err": "ERR",
    "warning": "WRN",
    "notice": "NTC",
    "info": "INF",
    "debug": "DBG",
}

PRIORITY_NUM_TO_NAME = {
    "0": "emerg",
    "1": "alert",
    "2": "crit",
    "3": "err",
    "4": "warning",
    "5": "notice",
    "6": "info",
    "7": "debug",
}


@dataclass
class LogEntry:
    styled: Text
    plain: str
    severity: str | None = None
    timestamp: datetime | None = None

    def matches(self, severities: set[str] | None, since: datetime | None) -> bool:
        # Entries with no known severity/timestamp (anything that isn't
        # journalctl/dmesg output, or a line that failed to parse) always
        # pass through: the filters can only narrow down what they're able
        # to classify, not silently swallow everything else.
        if (
            severities
            and self.severity is not None
            and self.severity not in severities
        ):
            return False
        if since is not None and self.timestamp is not None and self.timestamp < since:
            return False
        return True


def _dot(level_name: str) -> Text:
    # Style only the dot itself: Text(DOT, style=color) would set that
    # color as the object's *base* style, which Rich then applies to
    # everything appended afterwards too, tinting the whole line.
    color = SEVERITY_COLORS.get(level_name, DEFAULT_COLOR)
    text = Text()
    text.append(DOT, style=color)
    return text


def _plain_entry(text: str) -> LogEntry:
    return LogEntry(styled=Text(text), plain=text)


def format_journal_line(raw_line: str) -> LogEntry | None:
    """Reformat one line of `journalctl --output=json` into a colored line."""
    raw_line = raw_line.strip()
    if not raw_line:
        return None

    try:
        entry = json.loads(raw_line)
    except ValueError:
        # Not JSON (e.g. journalctl's own catalog/explain text with -xe) --
        # show it as-is rather than dropping it.
        return _plain_entry(raw_line)

    level = PRIORITY_NUM_TO_NAME.get(str(entry.get("PRIORITY", "")), "info")

    timestamp: datetime | None = None
    realtime = entry.get("__REALTIME_TIMESTAMP")
    if realtime:
        try:
            timestamp = datetime.fromtimestamp(int(realtime) / 1_000_000)
        except (ValueError, OSError, OverflowError):
            timestamp = None

    identifier = entry.get("SYSLOG_IDENTIFIER") or entry.get("_COMM") or ""
    pid = entry.get("_PID")
    if identifier and pid:
        identifier = f"{identifier}[{pid}]"

    message = entry.get("MESSAGE", "")
    if isinstance(message, list):
        # Non-UTF8 messages are sent as an array of byte values.
        try:
            message = bytes(message).decode(errors="replace")
        except (TypeError, ValueError):
            message = str(message)

    timestamp_label = timestamp.strftime("%b %d %H:%M:%S") if timestamp else ""

    line = _dot(level)
    prefix = " ".join(part for part in (timestamp_label, identifier) if part)
    line.append(f" {prefix}: " if prefix else " ")
    line.append(str(message))

    return LogEntry(styled=line, plain=line.plain, severity=level, timestamp=timestamp)


_DMESG_LINE_RE = re.compile(
    r"^(?P<fac>\S+)\s*:(?P<level>\S+)\s*:\s*\[(?P<ts>[^\]]*)\]\s?(?P<msg>.*)$"
)


def format_dmesg_line(raw_line: str) -> LogEntry | None:
    """Reformat one line of `dmesg -x -T` (decoded, human timestamp) output."""
    raw_line = raw_line.rstrip("\n")
    if not raw_line.strip():
        return None

    match = _DMESG_LINE_RE.match(raw_line)
    if not match:
        return _plain_entry(raw_line)

    level = match.group("level").strip()
    facility = match.group("fac").strip()
    timestamp_raw = match.group("ts").strip()
    message = match.group("msg")

    timestamp: datetime | None = None
    try:
        timestamp = datetime.strptime(timestamp_raw, "%a %b %d %H:%M:%S %Y")
    except ValueError:
        timestamp = None

    line = _dot(level)
    prefix = " ".join(part for part in (timestamp_raw, facility) if part)
    line.append(f" {prefix}: " if prefix else " ")
    line.append(message)

    return LogEntry(styled=line, plain=line.plain, severity=level, timestamp=timestamp)
