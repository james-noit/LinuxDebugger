"""A real, PTY-backed terminal embedded in the app -- not a one-shot
command runner that captures stdout and prints it back. It spawns the
user's actual login shell attached to a pseudo-terminal, so it gets
everything a real terminal gives it for free: the shell's own prompt
(user, host, cwd, colors -- whatever the user's own shell config already
renders), ordinary commands' isatty()-gated color output, and genuine
interactivity for anything that requires a controlling terminal (`sudo`
prompting for a password in place, `systemctl edit` invoking $EDITOR,
`less`, `vim`, ...).

A pyte virtual screen decodes the PTY's byte stream so escape sequences
(including a bare `clear`) only ever repaint pyte's own off-screen
buffer -- they never reach the real terminal Textual itself is drawing
to, which is what let a stray `clear` corrupt the whole app under the
previous line-input-and-captured-output design this replaces.
"""

import fcntl
import os
import pty
import signal
import struct
import termios
from asyncio import get_running_loop

import pyte
from rich.color import Color as RichColor
from rich.text import Text
from textual import events
from textual.containers import Vertical
from textual.message import Message
from textual.widget import Widget

# pyte's own ANSI color name table (pyte.graphics.FG_ANSI/FG_AIXTERM) calls
# index 3 "brown" and its bold/AIXTERM variant "brightbrown" -- a historical
# xterm-ism, but not a name Rich recognizes (Rich calls that color
# "yellow"). Everything else lines up except the "bright*" prefix needing
# an underscore.
_PYTE_COLOR_ALIASES = {
    "brown": "yellow",
    "brightbrown": "bright_yellow",
    "brightblack": "bright_black",
    "brightred": "bright_red",
    "brightgreen": "bright_green",
    "brightyellow": "bright_yellow",
    "brightblue": "bright_blue",
    "brightmagenta": "bright_magenta",
    "brightcyan": "bright_cyan",
    "brightwhite": "bright_white",
}

_HEX_DIGITS = set("0123456789abcdefABCDEF")

# Memoized rather than re-parsed per cell per frame -- this runs on every
# visible character of every redraw.
_color_validity_cache: dict[str, bool] = {}


def _is_valid_rich_color(name: str) -> bool:
    valid = _color_validity_cache.get(name)
    if valid is None:
        try:
            RichColor.parse(name)
            valid = True
        except Exception:
            valid = False
        _color_validity_cache[name] = valid
    return valid


def _pyte_color_to_rich(color: str | None) -> str | None:
    """Never lets an unrecognized pyte color name reach Rich unvalidated --
    pyte's name table has had typos before (its own BG_AIXTERM table
    misspells "brightmagenta" as "bfightmagenta" as of 0.8.2) and a bad
    name here previously crashed the whole app with a MissingStyle error
    the moment a command's output used it. Falling back to "no color" for
    anything unrecognized degrades a wrong/odd color into a visual
    inaccuracy instead of a crash."""
    if not color or color == "default":
        return None
    if len(color) == 6 and all(c in _HEX_DIGITS for c in color):
        return f"#{color}"
    name = _PYTE_COLOR_ALIASES.get(color, color)
    return name if _is_valid_rich_color(name) else None


# Byte sequences a real terminal would send for non-printable keys --
# standard xterm encodings. Printable characters (letters, digits,
# punctuation) aren't listed here; they're handled separately via
# event.character, since enumerating every possible printable key isn't
# practical (and would drift from whatever layout/locale is active).
_KEY_BYTES: dict[str, bytes] = {
    "enter": b"\r",
    "escape": b"\x1b",
    "tab": b"\t",
    "shift+tab": b"\x1b[Z",
    "backspace": b"\x7f",
    "delete": b"\x1b[3~",
    "up": b"\x1b[A",
    "down": b"\x1b[B",
    "right": b"\x1b[C",
    "left": b"\x1b[D",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "insert": b"\x1b[2~",
    "space": b" ",
}
_KEY_BYTES.update({f"ctrl+{chr(c)}": bytes([c - 96]) for c in range(ord("a"), ord("z") + 1)})
_KEY_BYTES.update(
    {
        f"f{n}": f"\x1b[{code}~".encode()
        for n, code in {
            1: 11, 2: 12, 3: 13, 4: 14, 5: 15, 6: 17,
            7: 18, 8: 19, 9: 20, 10: 21, 11: 23, 12: 24,
        }.items()
    }
)


class Terminal(Widget):
    """The actual VT100-ish screen + keyboard-forwarding logic. Has no
    BINDINGS of its own -- every key it doesn't explicitly recognize (and
    even most it does) is forwarded straight to the shell, otherwise
    common terminal editing (Ctrl+K, Ctrl+W, Escape inside vim, ...)
    would collide with app-level shortcuts of the same name. The single
    exception is `reserved_key` (the console's own open/close shortcut):
    that one is deliberately left alone so it bubbles up and closes the
    console instead of being swallowed -- without this there'd be no way
    out of a full-screen program like vim without killing the app.
    """

    can_focus = True

    DEFAULT_CSS = """
    Terminal {
        background: $surface;
    }
    """

    class Exited(Message):
        """The shell process ended on its own (`exit`, Ctrl+D, the shell
        crashing, ...) -- as opposed to this widget being torn down by
        the app itself (moving the console, closing the app), which
        doesn't post this. A dead shell sitting there frozen has no
        further use, so the app respawns a fresh one on next open rather
        than reusing it."""

    def __init__(self, *, reserved_key: str, shell: str | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._reserved_key = reserved_key
        self._shell = shell or os.environ.get("SHELL") or "/bin/sh"
        self._master_fd: int | None = None
        self._pid: int | None = None
        self._screen: pyte.Screen | None = None
        self._stream: pyte.Stream | None = None

    def on_mount(self) -> None:
        self._start()

    def _start(self) -> None:
        cols = max(self.size.width, 1) or 80
        rows = max(self.size.height, 1) or 24
        self._screen = pyte.Screen(cols, rows)
        self._stream = pyte.Stream(self._screen)

        pid, master_fd = pty.fork()
        if pid == 0:
            # Child: replace this process image entirely, so nothing
            # about the parent's asyncio loop/open fds carries over.
            os.environ["TERM"] = "xterm-256color"
            try:
                os.execvp(self._shell, [self._shell, "-i"])
            except OSError:
                os._exit(1)

        self._pid = pid
        self._master_fd = master_fd
        self._set_winsize(rows, cols)
        os.set_blocking(master_fd, False)
        get_running_loop().add_reader(master_fd, self._on_master_readable)

    def _set_winsize(self, rows: int, cols: int) -> None:
        if self._master_fd is None:
            return
        try:
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
        except OSError:
            pass

    def _on_master_readable(self) -> None:
        assert self._master_fd is not None
        try:
            data = os.read(self._master_fd, 65536)
        except OSError:
            data = b""
        if not data:
            self._shut_down()
            self.refresh()
            self.post_message(self.Exited())
            return
        self._stream.feed(data.decode(errors="replace"))
        self.refresh()

    def _shut_down(self) -> None:
        if self._master_fd is not None:
            loop = get_running_loop()
            try:
                loop.remove_reader(self._master_fd)
            except (ValueError, OSError):
                pass
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._pid is not None:
            try:
                os.waitpid(self._pid, 0)
            except ChildProcessError:
                pass
            self._pid = None

    def on_unmount(self) -> None:
        if self._pid is not None:
            try:
                os.kill(self._pid, signal.SIGHUP)
            except OSError:
                pass
        self._shut_down()

    def _on_resize(self, event: events.Resize) -> None:
        if self._screen is None:
            return
        cols = max(event.size.width, 1)
        rows = max(event.size.height, 1)
        self._screen.resize(rows, cols)
        self._set_winsize(rows, cols)
        if self._pid is not None:
            try:
                os.killpg(os.getpgid(self._pid), signal.SIGWINCH)
            except OSError:
                pass
        self.refresh()

    def render(self) -> Text:
        if self._screen is None:
            return Text("")
        text = Text()
        cursor = self._screen.cursor
        show_cursor = self.has_focus and not cursor.hidden
        for y in range(self._screen.lines):
            line = self._screen.buffer[y]
            for x in range(self._screen.columns):
                char = line[x]
                fg = _pyte_color_to_rich(char.fg)
                bg = _pyte_color_to_rich(char.bg)
                if char.reverse:
                    fg, bg = bg, fg
                if show_cursor and y == cursor.y and x == cursor.x:
                    fg, bg = bg, fg  # reverse-video swap, doubling as the cursor block
                    fg = fg or "black"
                    bg = bg or "white"
                style_parts = []
                if fg:
                    style_parts.append(fg)
                if bg:
                    style_parts.append(f"on {bg}")
                if char.bold:
                    style_parts.append("bold")
                if char.italics:
                    style_parts.append("italic")
                if char.underscore:
                    style_parts.append("underline")
                if char.strikethrough:
                    style_parts.append("strike")
                text.append(char.data or " ", style=" ".join(style_parts) or None)
            if y < self._screen.lines - 1:
                text.append("\n")
        return text

    async def on_key(self, event: events.Key) -> None:
        if event.key == self._reserved_key:
            return
        data = _KEY_BYTES.get(event.key)
        if data is None and event.is_printable and event.character:
            data = event.character.encode("utf-8", errors="ignore")
        if data is None:
            return
        event.prevent_default()
        event.stop()
        if self._master_fd is not None:
            try:
                os.write(self._master_fd, data)
            except OSError:
                pass


class Console(Vertical):
    """Docked to the bottom or right of the screen by app.py (see
    Settings.console_position); this widget just wraps Terminal for a
    consistent border/title, and exposes focus() so app.py doesn't need
    to know Terminal exists.
    """

    DEFAULT_CSS = """
    Console {
        border: round $primary;
    }
    Console.-position-bottom {
        height: 16;
        width: 1fr;
    }
    Console.-position-right {
        width: 82;
        height: 1fr;
    }
    Console Terminal {
        height: 1fr;
        width: 1fr;
    }
    """

    def __init__(self, *, reserved_key: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._reserved_key = reserved_key
        self.border_title = "Console"
        self.border_subtitle = f"{reserved_key} close · a real shell -- sudo, $EDITOR, colors all just work"

    def compose(self):
        yield Terminal(reserved_key=self._reserved_key)

    def focus_input(self) -> None:
        self.query_one(Terminal).focus()
