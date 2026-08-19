"""Small persisted-settings layer for cross-session preferences (currently
just the console's dock side and its keyboard shortcut). A JSON file under
XDG_CONFIG_HOME (or ~/.config as the fallback) rather than a database --
there's exactly a handful of scalar values here, nothing that needs a
schema or migrations.
"""

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

# New keybindings can be added here over time; load_settings() merges
# stored values over this default, so an existing settings.json that
# predates a newly-added action still gets that action's default instead
# of a missing key.
DEFAULT_KEYBINDINGS: dict[str, str] = {
    "toggle_console": "f9",
}


def settings_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else Path.home() / ".config"
    return base / "linuxdebugger" / "settings.json"


@dataclass
class Settings:
    # None until the console is opened for the first time and the user is
    # asked; "bottom" or "right" after that.
    console_position: str | None = None
    keybindings: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_KEYBINDINGS))


def load_settings() -> Settings:
    try:
        raw = json.loads(settings_path().read_text())
    except (OSError, json.JSONDecodeError):
        return Settings()

    keybindings = dict(DEFAULT_KEYBINDINGS)
    stored_keybindings = raw.get("keybindings")
    if isinstance(stored_keybindings, dict):
        keybindings.update(stored_keybindings)

    console_position = raw.get("console_position")
    if console_position not in ("bottom", "right"):
        console_position = None

    return Settings(console_position=console_position, keybindings=keybindings)


def save_settings(settings: Settings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2) + "\n")
