from ..commands import CommandPanel


class LinuxDebuggerPlugin:
    """Base class for a plugin that contributes one or more panels.

    Subclasses override `name`, `is_available()`, and `panels()`. A plugin
    reporting `is_available() -> False` (e.g. required hardware isn't
    present) is skipped silently -- not treated as an error, the same way
    macros/common.py's `which()` lets a probe degrade gracefully instead
    of crashing.
    """

    name: str = "unnamed-plugin"

    def is_available(self) -> bool:
        return True

    def panels(self) -> list[CommandPanel]:
        raise NotImplementedError
