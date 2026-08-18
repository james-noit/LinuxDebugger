"""Shared building blocks for every macro across every panel.

A macro runs a small decision tree of probes -- kernel/sysfs reads first
(zero dependency), external tools only after `_which` confirms they're
installed -- and reduces the result to a fixed set of `StatusItem` rows.
`MacroResult.kind` picks how MacroView renders those rows: a plain
label/value list, a semaphore (traffic-light) panel, a pass/fail ladder, or
a percentage gauge. Every macro shares this same shape so a future live-
updating monitor can re-run the same probes and re-render the same rows
with fresh values.
"""

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from typing import Awaitable, Callable

UNKNOWN = "unknown"

# Every parser in this package matches against known-English output
# ("Kernel driver in use:", "OpenGL renderer string:", "yes"/"no" fields,
# English month names in dmesg -T...). Without forcing the C locale, tools
# like nmcli silently localize their machine-readable output (observed:
# "sí" instead of "yes" for nmcli -t under a Spanish locale), breaking the
# parse without raising any error at all.
_PROBE_ENV = dict(os.environ, LC_ALL="C", LANG="C")


@dataclass(frozen=True)
class StatusItem:
    """One row of a macro's result.

    `level` drives semaphore/ladder coloring ("ok" | "warn" | "crit" |
    "unknown" | "neutral"); `percent` (0-100) drives the gauge kind's bar.
    Both are ignored by kinds that don't use them. `section`, when set,
    groups consecutive items under a subheader in MacroView -- items with
    no section (the default) render exactly as before, so this is opt-in
    per macro.
    """

    label: str
    value: str
    level: str = "neutral"
    percent: float | None = None
    section: str | None = None


@dataclass(frozen=True)
class MacroResult:
    title: str
    items: list[StatusItem]
    kind: str = "fields"  # "fields" | "semaphore" | "ladder" | "gauge"


@dataclass(frozen=True)
class MacroRun:
    result: MacroResult
    raw_log: str


@dataclass(frozen=True)
class MacroOption:
    """A configurable toggle for a macro -- the macro equivalent of a
    Command's `Flag`, minus the argv-token machinery (a macro option
    changes what the *Python* run() function does, not an argv it builds).

    Two use cases: gating what privilege level a step is allowed to use
    (`requires_sudo=True` -- the app prompts for a password before the run
    if any such option is checked), and picking which `StatusItem` rows to
    include in the output (`default=True` so the output starts "everything
    shown" and checkboxes narrow it down, the opposite default of a
    Command's flags which start unchecked and add on).

    `group`, when set, clusters consecutive options with the same value
    under a shared subheader in MacroOptionList -- options with no group
    (the default) render exactly as before, so this is opt-in per macro.
    """

    key: str
    label: str
    description: str
    default: bool = False
    requires_sudo: bool = False
    group: str | None = None


@dataclass(frozen=True, kw_only=True)
class Macro:
    name: str
    description: str
    # The commands a run of this macro can involve, for display in the
    # confirmation dialog before anything actually executes. Since this is
    # a decision tree, not every step necessarily runs on every machine --
    # each one is only used once the tree reaches it and (for external
    # tools) confirms it's actually installed.
    steps: tuple[tuple[str, ...], ...]
    run: Callable[..., Awaitable[MacroRun]]
    # Empty by default -- a macro with no options is called as `run()`,
    # same as before this existed. A macro that declares options is called
    # as `run(selected_option_keys, sudo_password)` instead.
    options: tuple[MacroOption, ...] = ()
    # True marks this macro as a narrower, standalone re-run of part of
    # the macro immediately above it in the same panel's list (e.g. "Basic
    # Firewall Check" under "Basic check") -- MacroList indents it and
    # prefixes it with a corner arrow instead of treating it as an
    # unrelated, independent macro. Purely a display hint: it doesn't
    # change confirmation, running, or option behavior at all.
    subordinate: bool = False


def which(binary: str) -> bool:
    return shutil.which(binary) is not None


async def exec_probe(argv: tuple[str, ...]) -> tuple[str | None, str]:
    """Runs a probe command once and returns (output, display_text).

    `output` is the command's stdout, but only when it actually succeeded
    -- None on failure, so field-parsing code can treat it as "no data"
    without needing its own success check. `display_text` is always
    populated (including the real error/stderr text on failure) so the raw
    log panel shows what actually happened instead of a generic
    placeholder.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_PROBE_ENV,
        )
    except FileNotFoundError:
        return None, "(command not found)"
    stdout, _ = await process.communicate()
    text = stdout.decode(errors="replace").rstrip()
    if process.returncode != 0:
        return None, text or f"(exited with code {process.returncode})"
    return text, text


async def exec_probe_grep(argv: tuple[str, ...]) -> tuple[str | None, str]:
    """Like `exec_probe`, but for grep-style tools (journalctl -g, grep
    itself...) where a non-zero exit conventionally just means "no matches"
    rather than a real failure. Only a missing binary counts as
    unavailable here; any exit code is treated as valid output so "zero
    matches" doesn't get misread as "tool unavailable"."""
    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_PROBE_ENV,
        )
    except FileNotFoundError:
        return None, "(command not found)"
    stdout, _ = await process.communicate()
    text = stdout.decode(errors="replace").rstrip()
    return text, text or "(no matches)"


async def exec_probe_sudo(argv: tuple[str, ...], password: str) -> tuple[str | None, str]:
    """Like `exec_probe`, but prefixes argv with `sudo -k -S` and feeds the
    password over stdin -- the same mechanism `_run_command` in app.py
    already uses for a sudo-required Command, just reused here for a
    single privileged macro step instead of a whole command.

    `_PROBE_ENV`'s LC_ALL=C doesn't survive sudo on its own: Ubuntu's
    default sudoers has `Defaults env_reset`, which strips the caller's
    LC_ALL/LANG before PAM re-populates them from the *target* user's
    locale (root's, via /etc/default/locale) -- not ours. Without a
    SETENV tag, `sudo LC_ALL=C cmd` is rejected outright, so `env` is
    inserted after sudo instead: it's an ordinary command from sudo's
    point of view (no env-filtering applies to it), and once it's running
    as root it sets its own child's environment directly."""
    full_argv = ("sudo", "-k", "-S", "-p", "", "env", "LC_ALL=C", "LANG=C", *argv)
    try:
        process = await asyncio.create_subprocess_exec(
            *full_argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=_PROBE_ENV,
        )
    except FileNotFoundError:
        return None, "(sudo not installed)"
    try:
        stdout, _ = await process.communicate((password + "\n").encode())
    except (BrokenPipeError, ConnectionResetError):
        stdout = b""
    text = stdout.decode(errors="replace").rstrip()
    if process.returncode != 0:
        return None, text or f"(exited with code {process.returncode})"
    return text, text


class RawLog:
    """Accumulates the raw '$ command\\noutput' chunks a macro run shows in
    the Log output pane, and the `probe()` helper macros use to both run a
    command and record it in the same call."""

    def __init__(self) -> None:
        self._chunks: list[str] = []

    def note(self, header: str, body: str) -> None:
        self._chunks.append(f"$ {header}\n{body}\n")

    async def probe(self, argv: tuple[str, ...], grep: bool = False) -> str | None:
        output, display_text = await (exec_probe_grep(argv) if grep else exec_probe(argv))
        self.note(" ".join(argv), display_text)
        return output

    async def probe_sudo(self, argv: tuple[str, ...], password: str | None) -> str | None:
        if password is None:
            self.note(f"sudo {' '.join(argv)}", "(sudo required but no password provided)")
            return None
        output, display_text = await exec_probe_sudo(argv, password)
        self.note(f"sudo {' '.join(argv)}", display_text)
        return output

    def text(self) -> str:
        return "\n".join(self._chunks)
