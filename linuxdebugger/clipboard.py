"""Clipboard helper: prefer a native X11/Wayland clipboard tool, fall back to
Textual's OSC52 escape-sequence copy (which also works over SSH)."""

import shutil
import subprocess

_CLIPBOARD_COMMANDS = (
    ["wl-copy"],
    ["xclip", "-selection", "clipboard"],
    ["xsel", "--clipboard", "--input"],
)


def copy_to_clipboard(app, text: str) -> bool:
    if not text:
        return False

    for cmd in _CLIPBOARD_COMMANDS:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(cmd, input=text.encode(), timeout=2, check=True)
            return True
        except Exception:
            continue

    try:
        app.copy_to_clipboard(text)
        return True
    except Exception:
        return False
