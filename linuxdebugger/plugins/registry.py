import logging

from ..commands import CommandPanel
from .base import LinuxDebuggerPlugin

logger = logging.getLogger(__name__)


def discover_plugin_panels(
    plugin_classes: list[type[LinuxDebuggerPlugin]],
) -> list[CommandPanel]:
    """Instantiates each plugin class and collects its panels.

    A plugin that fails to construct, reports itself unavailable, or
    raises while building its panels is skipped -- logged as a warning,
    never allowed to crash startup. Doesn't care where `plugin_classes`
    came from, so smarter discovery (entry points, a config directory)
    can replace the hardcoded seed list in plugins/__init__.py later
    without changing this function or the plugin interface.
    """
    panels: list[CommandPanel] = []
    for plugin_class in plugin_classes:
        try:
            plugin = plugin_class()
            if not plugin.is_available():
                continue
            panels.extend(plugin.panels())
        except Exception:
            logger.warning(
                "Plugin %s failed to load", getattr(plugin_class, "name", plugin_class),
                exc_info=True,
            )
    return panels
