from typing import Callable

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..macros.common import StatusItem
from .macro_view import _render_gauge

REFRESH_INTERVAL = 1.0

# (label, unit, min, max) -- min/max bound the gauge's 0-100% scale, chosen
# to comfortably span typical indoor Sense HAT readings without the bar
# pinning at 0% or 100% under normal conditions.
_ENV_READINGS: tuple[tuple[str, str, float, float], ...] = (
    ("Temperature", "°C", 10.0, 40.0),
    ("Humidity", "%RH", 0.0, 100.0),
    ("Pressure", "mbar", 950.0, 1050.0),
)

# IMU axes are centered at 0, not naturally 0-100%, so they're rendered as
# a signed value against a fixed +/- range rather than reusing the gauge's
# percent bar.
_IMU_AXES: tuple[tuple[str, str, str], ...] = (
    ("accel", "Accelerometer", "g"),
    ("gyro", "Gyroscope", "rad/s"),
    ("compass", "Magnetometer", "µT"),
)


def _load_sense_hat_class():
    try:
        from sense_hat import SenseHat
    except (ImportError, OSError):
        return None
    return SenseHat


class SenseHatView(VerticalScroll):
    """Live-updating dashboard for a Raspberry Pi Sense HAT's environmental
    and orientation sensors.

    Reuses macro_view's gauge renderer/StatusItem shape -- exactly the
    "future live-updating monitor" its docstring anticipates re-running a
    template with fresh values on a timer instead of a one-time snapshot.
    """

    DEFAULT_CSS = """
    SenseHatView {
        padding: 0 1;
    }
    """

    can_focus = True

    def __init__(
        self,
        *,
        sense_hat_factory: Callable[[], object] | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.border_title = "Sensor HAT"
        self._sense_hat_factory = sense_hat_factory or _load_sense_hat_class()
        self._sense = None

    def compose(self):
        yield Static("", id="body")

    def on_mount(self) -> None:
        try:
            self._sense = self._sense_hat_factory()
        except Exception as error:
            self._show_error(f"Sense HAT unavailable: {error}")
            return
        self._refresh()
        self.set_interval(REFRESH_INTERVAL, self._refresh)

    def _show_error(self, message: str) -> None:
        self.query_one("#body", Static).update(message)

    def _refresh(self) -> None:
        if self._sense is None:
            return
        items: list[StatusItem] = []
        try:
            items.extend(self._environmental_items())
            items.extend(self._imu_items())
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
        items: list[StatusItem] = []
        for label, unit, low, high in _ENV_READINGS:
            try:
                value = readers[label]()
            except Exception:
                items.append(StatusItem(label=label, value="unavailable", level="unknown"))
                continue
            percent = max(0.0, min(100.0, (value - low) / (high - low) * 100))
            items.append(
                StatusItem(
                    label=label,
                    value=f"{value:.1f}{unit}",
                    level="ok",
                    percent=percent,
                    section="Environment",
                )
            )
        return items

    def _imu_items(self) -> list[StatusItem]:
        readers = {
            "accel": self._sense.get_accelerometer_raw,
            "gyro": self._sense.get_gyroscope_raw,
            "compass": self._sense.get_compass_raw,
        }
        items: list[StatusItem] = []
        for key, label, unit in _IMU_AXES:
            try:
                axes = readers[key]()
                value = f"x={axes['x']:.2f} y={axes['y']:.2f} z={axes['z']:.2f} {unit}"
                level = "neutral"
            except Exception:
                value = "unavailable"
                level = "unknown"
            items.append(StatusItem(label=label, value=value, level=level, section="Orientation"))
        return items
