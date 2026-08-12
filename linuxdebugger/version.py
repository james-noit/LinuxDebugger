import os
from pathlib import Path

VERSION_ENV_VAR = "LINUXDEBUGGER_VERSION"
_VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"


def load_version() -> str:
    """Read VERSION from the project root and expose it as an env var."""
    try:
        version = _VERSION_FILE.read_text().strip()
    except OSError:
        version = "unknown"
    os.environ[VERSION_ENV_VAR] = version
    return version


def get_version() -> str:
    return os.environ.get(VERSION_ENV_VAR) or load_version()
