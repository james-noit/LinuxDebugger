import asyncio
from collections import deque
from typing import Callable

from rich.text import Text
from textual import events
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import Static

from ..macros.common import StatusItem
from ..settings import load_settings
from .macro_view import _render_gauge

JOYSTICK_POLL_INTERVAL = 0.2
HISTORY_LENGTH = 60
CPU_THERMAL_ZONE = "/sys/class/thermal/thermal_zone0/temp"

# (label, unit, min, max) -- min/max bound the gauge's 0-100% scale, chosen
# to comfortably span typical indoor Sense HAT readings without the bar
# pinning at 0% or 100% under normal conditions.
_ENV_READINGS: tuple[tuple[str, str, float, float], ...] = (
    ("Temperature", "°C", 10.0, 40.0),
    ("Humidity", "%RH", 0.0, 100.0),
    ("Pressure", "mbar", 950.0, 1050.0),
)

# (warn low, ok low, ok high, warn high) -- outside the warn bounds is
# "crit", between warn and ok is "warn", inside ok is "ok". Soft, generally
# reasonable indoor ranges rather than precise thresholds.
_THRESHOLDS: dict[str, tuple[float, float, float, float]] = {
    "Temperature": (0.0, 10.0, 32.0, 40.0),
    "Humidity": (10.0, 20.0, 70.0, 85.0),
    "Pressure": (950.0, 970.0, 1040.0, 1050.0),
}

_ORIENTATION_AXES: tuple[str, ...] = ("pitch", "roll", "yaw")

_COMPASS_POINTS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
_COMPASS_ARROWS = ("↑", "↗", "→", "↘", "↓", "↙", "←", "↖")

_SPARKLINE_LEVELS = " ▁▂▃▄▅▆▇█"

# A recognizable 8-row rainbow stripe, used as the LED matrix "test
# pattern" -- easy to tell apart from a bug (blank/wrong matrix) at a
# glance.
_TEST_PATTERN_COLORS: tuple[tuple[int, int, int], ...] = (
    (255, 0, 0), (255, 127, 0), (255, 255, 0), (0, 255, 0),
    (0, 255, 255), (0, 0, 255), (139, 0, 255), (255, 255, 255),
)


def _load_sense_hat_class():
    try:
        from sense_hat import SenseHat
    except (ImportError, OSError):
        return None
    return SenseHat


def _level_for(label: str, value: float) -> str:
    thresholds = _THRESHOLDS.get(label)
    if thresholds is None:
        return "ok"
    crit_low, warn_low, warn_high, crit_high = thresholds
    if value < crit_low or value > crit_high:
        return "crit"
    if value < warn_low or value > warn_high:
        return "warn"
    return "ok"


def _read_cpu_temperature() -> float | None:
    try:
        with open(CPU_THERMAL_ZONE) as handle:
            return int(handle.read().strip()) / 1000.0
    except (OSError, ValueError):
        return None


def _correct_temperature(raw: float, cpu_temp: float | None, factor: float) -> float:
    """Community-derived correction for the Sense HAT's CPU-heat bias --
    see settings.py's DEFAULT_SENSE_HAT_TEMP_CALIBRATION_FACTOR docstring.
    Falls back to the raw value when the CPU temperature can't be read
    (e.g. not actually on a Pi)."""
    if cpu_temp is None or factor <= 0:
        return raw
    return raw - ((cpu_temp - raw) / factor)


def _sparkline(values: deque[float]) -> str:
    if len(values) < 2:
        return ""
    low, high = min(values), max(values)
    span = high - low
    if span == 0:
        mid = _SPARKLINE_LEVELS[len(_SPARKLINE_LEVELS) // 2]
        return mid * len(values)
    steps = len(_SPARKLINE_LEVELS) - 1
    return "".join(
        _SPARKLINE_LEVELS[round((value - low) / span * steps)] for value in values
    )


def _compass_label(degrees: float) -> str:
    index = round(degrees / 45) % 8
    return f"{_COMPASS_POINTS[index]} {_COMPASS_ARROWS[index]}"


def _test_pattern() -> list[tuple[int, int, int]]:
    return [_TEST_PATTERN_COLORS[row] for row in range(8) for _col in range(8)]


class SenseHatView(VerticalScroll):
    """Live-updating dashboard for a Raspberry Pi Sense HAT.

    Reuses macro_view's gauge renderer/StatusItem shape -- exactly the
    "future live-updating monitor" its docstring anticipates re-running a
    template with fresh values on a timer instead of a one-time snapshot.

    Also a two-way interface: 't'/'c'/'m' drive the physical LED matrix,
    and the physical joystick's left/right (when present) switch panels
    the same way Ctrl+Left/Right do while this panel is active.
    """

    DEFAULT_CSS = """
    SenseHatView {
        padding: 0 1;
    }
    """

    can_focus = True

    class NavigatePanel(Message):
        def __init__(self, direction: int) -> None:
            self.direction = direction
            super().__init__()

    def __init__(
        self,
        *,
        sense_hat_factory: Callable[[], object] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.border_title = "Sensor HAT"
        self.border_subtitle = "t: LED pattern · c: LED clear · m: LED temp"
        self._sense_hat_factory = sense_hat_factory or _load_sense_hat_class()
        self._sense = None
        settings = load_settings()
        self._calibration_factor = settings.sense_hat_temp_calibration_factor
        self._refresh_interval = settings.sense_hat_refresh_interval
        self._history: dict[str, deque[float]] = {
            label: deque(maxlen=HISTORY_LENGTH) for label, *_ in _ENV_READINGS
        }

    def compose(self):
        yield Static("", id="body")

    def on_mount(self) -> None:
        try:
            self._sense = self._sense_hat_factory()
        except Exception as error:
            self._show_error(f"Sense HAT unavailable: {error}")
            return
        self._refresh()
        self.set_interval(self._refresh_interval, self._refresh)
        self.set_interval(JOYSTICK_POLL_INTERVAL, self._poll_joystick)

    def _show_error(self, message: str) -> None:
        self.query_one("#body", Static).update(message)

    def _refresh(self) -> None:
        if self._sense is None:
            return
        items: list[StatusItem] = []
        try:
            items.extend(self._environmental_items())
            items.extend(self._orientation_items())
            items.append(self._compass_item())
        except Exception as error:
            self._show_error(f"Sense HAT disconnected: {error}")
            return
        if not items:
            self._show_error("Sense HAT disconnected")
            return
        text: Text = _render_gauge("Sense HAT", items)
        self.query_one("#body", Static).update(text)

    def _environmental_items(self) -> list[StatusItem]:
        readers = {
            "Temperature": self._sense.get_temperature,
            "Humidity": self._sense.get_humidity,
            "Pressure": self._sense.get_pressure,
        }
        cpu_temp = _read_cpu_temperature()
        items: list[StatusItem] = []
        for label, unit, low, high in _ENV_READINGS:
            try:
                raw_value = readers[label]()
            except Exception:
                items.append(StatusItem(label=label, value="unavailable", level="unknown"))
                continue

            if label == "Temperature":
                value = _correct_temperature(raw_value, cpu_temp, self._calibration_factor)
                suffix = f" (raw {raw_value:.1f}{unit})" if cpu_temp is not None else ""
            else:
                value = raw_value
                suffix = ""

            self._history[label].append(value)
            percent = max(0.0, min(100.0, (value - low) / (high - low) * 100))
            items.append(
                StatusItem(
                    label=label,
                    value=f"{value:.1f}{unit}{suffix}  {_sparkline(self._history[label])}",
                    level=_level_for(label, value),
                    percent=percent,
                    section="Environment",
                )
            )
        return items

    def _orientation_items(self) -> list[StatusItem]:
        # Fused pitch/roll/yaw (sensor-fusion of accel+gyro+magnetometer)
        # is far more stable to read at a glance than the three raw IMU
        # vectors it's derived from.
        try:
            orientation = self._sense.get_orientation()
        except Exception:
            return [
                StatusItem(label=axis.capitalize(), value="unavailable", level="unknown", section="Orientation")
                for axis in _ORIENTATION_AXES
            ]
        items = []
        for axis in _ORIENTATION_AXES:
            degrees = orientation.get(axis, 0.0)
            percent = max(0.0, min(100.0, degrees / 360 * 100))
            items.append(
                StatusItem(
                    label=axis.capitalize(),
                    value=f"{degrees:5.1f}°",
                    level="neutral",
                    percent=percent,
                    section="Orientation",
                )
            )
        return items

    def _compass_item(self) -> StatusItem:
        try:
            heading = self._sense.get_compass()
            value = f"{heading:5.1f}°  {_compass_label(heading)}"
            level = "neutral"
        except Exception:
            value = "unavailable"
            level = "unknown"
        return StatusItem(label="Compass", value=value, level=level, section="Orientation")

    # -- LED matrix (two-way interface) ----------------------------------

    def on_key(self, event: events.Key) -> None:
        if self._sense is None:
            return
        if event.key == "t":
            self._run_led(self._sense.set_pixels, _test_pattern())
            event.stop()
        elif event.key == "c":
            self._run_led(self._sense.clear)
            event.stop()
        elif event.key == "m":
            temp = self._history["Temperature"][-1] if self._history["Temperature"] else None
            if temp is not None:
                self._run_led(self._sense.show_message, f"{temp:.1f}C", 0.05)
            event.stop()

    def _run_led(self, fn: Callable, *args) -> None:
        # LED matrix writes (especially show_message's scroll) block for
        # a while -- run them off the event loop thread so they don't
        # freeze the rest of the UI.
        self.run_worker(asyncio.to_thread(fn, *args), exclusive=True, group="sense-hat-led")

    # -- joystick (physical panel navigation) -----------------------------

    def _poll_joystick(self) -> None:
        if self._sense is None:
            return
        try:
            stick_events = self._sense.stick.get_events()
        except Exception:
            return
        for stick_event in stick_events:
            if stick_event.action != "pressed":
                continue
            if stick_event.direction == "right":
                self.post_message(self.NavigatePanel(1))
            elif stick_event.direction == "left":
                self.post_message(self.NavigatePanel(-1))
