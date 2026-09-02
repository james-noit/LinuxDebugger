from ..commands import CommandPanel
from ..widgets.sense_hat_view import SenseHatView
from .base import LinuxDebuggerPlugin


def load_sense_hat_class():
    """Imports and returns the `SenseHat` class, or None if it can't be
    used on this machine.

    `sense_hat` raises OSError (not just ImportError) when the package is
    installed but the I2C bus/device isn't there -- i.e. this isn't
    actually a Pi with the HAT attached -- so both must be caught for the
    plugin to degrade gracefully on a regular dev machine.
    """
    try:
        from sense_hat import SenseHat
    except (ImportError, OSError):
        return None
    return SenseHat


class SenseHatPlugin(LinuxDebuggerPlugin):
    name = "sense-hat"

    def is_available(self) -> bool:
        return load_sense_hat_class() is not None

    def panels(self) -> list[CommandPanel]:
        return [
            CommandPanel(
                name="Sensor HAT",
                commands=[],
                macros=[],
                content_factory=SenseHatView,
            )
        ]
