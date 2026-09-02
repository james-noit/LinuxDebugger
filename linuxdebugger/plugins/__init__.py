from .base import LinuxDebuggerPlugin
from .registry import discover_plugin_panels
from .sensehat import SenseHatPlugin

# The seed list of known plugin classes -- a stand-in for smarter discovery
# (entry points, a config directory) that can replace this later without
# changing discover_plugin_panels() or the plugin interface itself.
PLUGIN_CLASSES: list[type[LinuxDebuggerPlugin]] = [
    SenseHatPlugin,
]

__all__ = ["LinuxDebuggerPlugin", "discover_plugin_panels", "PLUGIN_CLASSES"]
