"""System Check panel macros.

The panel is meant to grow incrementally ("bit by bit"): each check is its
own macro, added over time, all sharing the same kernel/file-first decision
tree philosophy as the other panels' macros.
"""

import os
from dataclasses import replace

from .common import Macro, MacroOption, MacroResult, MacroRun, RawLog, StatusItem
from .firewall import FIREWALL_CHECK, FIREWALL_CHECK_OPTIONS, collect_firewall_items

PRIVILEGED_GROUP_NAMES = ("root", "sudo", "wheel", "admin")


def _parse_passwd() -> list[tuple[str, int, int]]:
    """Pure /etc/passwd parse -- zero dependency, world-readable on every
    Linux system. Returns (username, uid, gid) per entry."""
    users: list[tuple[str, int, int]] = []
    try:
        with open("/etc/passwd") as f:
            for line in f:
                fields = line.rstrip("\n").split(":")
                if len(fields) < 4:
                    continue
                name = fields[0]
                try:
                    uid = int(fields[2])
                    gid = int(fields[3])
                except ValueError:
                    continue
                users.append((name, uid, gid))
    except OSError:
        pass
    return users


def _parse_group() -> dict[str, tuple[int, list[str]]]:
    """Pure /etc/group parse -- zero dependency. Returns
    {group_name: (gid, [explicit member usernames])}."""
    groups: dict[str, tuple[int, list[str]]] = {}
    try:
        with open("/etc/group") as f:
            for line in f:
                fields = line.rstrip("\n").split(":")
                if len(fields) < 4:
                    continue
                name = fields[0]
                try:
                    gid = int(fields[2])
                except ValueError:
                    continue
                members = [m for m in fields[3].split(",") if m]
                groups[name] = (gid, members)
    except OSError:
        pass
    return groups


def _sudoers_paths() -> list[str]:
    paths = ["/etc/sudoers"]
    sudoers_d = "/etc/sudoers.d"
    if os.path.isdir(sudoers_d):
        try:
            paths.extend(
                os.path.join(sudoers_d, name)
                for name in sorted(os.listdir(sudoers_d))
                if not name.startswith(".") and name != "README"
            )
        except OSError:
            pass
    return paths


def _extract_sudoers_usernames(text: str) -> list[str]:
    users: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) >= 2 and fields[0] != "Defaults" and not fields[0].startswith("%"):
            users.append(fields[0])
    return users


async def _read_sudoers_grants(
    log: RawLog, use_sudo: bool, password: str | None
) -> list[str] | None:
    """Best-effort read of explicit per-user sudo grants in /etc/sudoers
    and /etc/sudoers.d/*. Those are typically root-only (mode 0440), so a
    plain read degrades to "unreadable" rather than failing outright --
    unless the "require sudo" option is on, in which case it's read via
    `sudo cat` with the password the app already prompted for."""
    paths = _sudoers_paths()

    if use_sudo:
        output = await log.probe_sudo(("cat", *paths), password)
        return None if output is None else _extract_sudoers_usernames(output)

    users: list[str] = []
    raw_chunks: list[str] = []
    any_readable = False
    for path in paths:
        try:
            with open(path) as f:
                text = f.read()
        except OSError:
            continue
        any_readable = True
        raw_chunks.append(f"--- {path} ---\n{text}")
        users.extend(_extract_sudoers_usernames(text))

    log.note(
        "read /etc/sudoers /etc/sudoers.d/*",
        "\n".join(raw_chunks) if raw_chunks else "(not readable without elevated privileges)",
    )
    return users if any_readable else None


BASIC_CHECK_STEPS: tuple[tuple[str, ...], ...] = (
    ("read", "/etc/passwd"),
    ("read", "/etc/group"),
    ("read", "/etc/sudoers", "/etc/sudoers.d/*"),
    ("sudo", "cat", "/etc/sudoers", "/etc/sudoers.d/*"),
    ("which", "ufw", "firewall-cmd", "nft", "iptables"),
    ("systemctl", "is-active", "<detected firewall unit>"),
    ("systemctl", "is-enabled", "<detected firewall unit>"),
    ("sudo", "<detected firewall tool>", "<status/list-rules>"),
)

# Options are grouped in two kinds: one privilege toggle (off by default --
# elevating is opt-in), and a "show" toggle per output row (on by default,
# so out of the box the macro behaves exactly like before options existed;
# unchecking one narrows the output down instead of building it up, the
# opposite default of a Command's flags). They're also tagged with `group`
# so MacroOptionList clusters them by functionality ("Users & Groups" vs
# "Firewall") instead of one flat 14-item list -- the firewall options are
# the same MacroOption objects "Basic Firewall Check" uses on its own
# (tagged here rather than at the source, so that standalone macro's own
# option list stays header-free).
BASIC_CHECK_OPTIONS: tuple[MacroOption, ...] = (
    MacroOption(
        key="sudo_sudoers",
        label="Require sudo for sudoers detail",
        description=(
            "Prompts for your sudo password and reads /etc/sudoers and "
            "/etc/sudoers.d directly as root, instead of reporting that "
            "detail as unreadable. The password is used only for this "
            "run and is not stored."
        ),
        default=False,
        requires_sudo=True,
        group="Users & Groups",
    ),
    MacroOption(
        key="show_total_users",
        label="Show: Total local users",
        description="The total number of entries in /etc/passwd.",
        default=True,
        group="Users & Groups",
    ),
    MacroOption(
        key="show_uid0",
        label="Show: UID 0 (root) accounts",
        description="Every account whose UID is 0 -- normally just 'root'.",
        default=True,
        group="Users & Groups",
    ),
    MacroOption(
        key="show_priv_groups",
        label="Show: Privileged groups present",
        description="Which of root/sudo/wheel/admin actually exist on this system.",
        default=True,
        group="Users & Groups",
    ),
    MacroOption(
        key="show_group_members",
        label="Show: Users in privileged groups",
        description="Accounts that are members of (or have as their primary group) a privileged group.",
        default=True,
        group="Users & Groups",
    ),
    MacroOption(
        key="show_sudoers",
        label="Show: Explicit sudoers grants",
        description="Per-user grants listed directly in /etc/sudoers, separate from group membership.",
        default=True,
        group="Users & Groups",
    ),
    MacroOption(
        key="show_total_access",
        label="Show: Total accounts with root access",
        description="The union of all of the above -- every account that can act as root, one way or another.",
        default=True,
        group="Users & Groups",
    ),
) + tuple(replace(option, group="Firewall") for option in FIREWALL_CHECK_OPTIONS)


async def basic_check(
    selected: frozenset[str] = frozenset(), password: str | None = None
) -> MacroRun:
    log = RawLog()
    items: list[StatusItem] = []

    users = _parse_passwd()
    log.note("read /etc/passwd", f"{len(users)} entries")
    if "show_total_users" in selected:
        items.append(StatusItem("Total local users", str(len(users))))

    root_uid_users = sorted(name for name, uid, _gid in users if uid == 0)
    if "show_uid0" in selected:
        items.append(
            StatusItem(
                "UID 0 (root) accounts",
                f"{len(root_uid_users)}: {', '.join(root_uid_users)}" if root_uid_users else "none found",
                level="ok" if root_uid_users == ["root"] else "crit",
            )
        )

    groups = _parse_group()
    log.note("read /etc/group", f"{len(groups)} groups")
    present_priv_groups = [name for name in PRIVILEGED_GROUP_NAMES if name in groups]
    if "show_priv_groups" in selected:
        items.append(
            StatusItem(
                "Privileged groups present",
                ", ".join(present_priv_groups) if present_priv_groups else "none found",
                level="neutral",
            )
        )

    group_members: set[str] = set()
    for name in present_priv_groups:
        gid, members = groups[name]
        group_members.update(members)
        group_members.update(uname for uname, _uid, ugid in users if ugid == gid)

    if "show_group_members" in selected:
        items.append(
            StatusItem(
                "Users in privileged groups",
                f"{len(group_members)}: {', '.join(sorted(group_members))}" if group_members else "none found",
                level="neutral",
            )
        )

    use_sudo = "sudo_sudoers" in selected
    sudoers_users = await _read_sudoers_grants(log, use_sudo, password)
    if "show_sudoers" in selected:
        if sudoers_users is None:
            items.append(
                StatusItem(
                    "Explicit sudoers grants",
                    "unreadable (enable 'Require sudo for sudoers detail' to read it)",
                    level="unknown",
                )
            )
        else:
            items.append(
                StatusItem(
                    "Explicit sudoers grants",
                    f"{len(sudoers_users)}: {', '.join(sorted(set(sudoers_users)))}"
                    if sudoers_users
                    else "none found",
                    level="neutral",
                )
            )

    total_root_access = set(root_uid_users) | group_members | set(sudoers_users or [])
    if "show_total_access" in selected:
        items.append(
            StatusItem(
                "Total accounts with root access",
                f"{len(total_root_access)}: {', '.join(sorted(total_root_access))}"
                if total_root_access
                else "none found",
                level="crit" if len(total_root_access) == 0 else ("warn" if len(total_root_access) > 8 else "ok"),
            )
        )

    user_group_items = items
    fw_items = await collect_firewall_items(
        log,
        want_tool="show_tool" in selected,
        want_active="show_active" in selected,
        want_enabled="show_enabled" in selected,
        want_policy="show_policy" in selected,
        want_dos_limit="show_dos_limit" in selected,
        want_ports="show_ports" in selected,
        use_sudo="sudo_rules" in selected,
        password=password,
    )
    # Tagged retroactively (rather than passing a section into every
    # StatusItem(...) call above) so MacroView renders the two checks as
    # visually distinct sections in one combined output.
    items = [replace(item, section="Basic User & Group Check") for item in user_group_items] + [
        replace(item, section="Basic Firewall Check") for item in fw_items
    ]

    if not items:
        items.append(StatusItem("Nothing selected", "enable at least one 'Show:' option", level="unknown"))

    result = MacroResult(title="Basic check", items=items, kind="semaphore")
    return MacroRun(result=result, raw_log=log.text())


SYSTEM_CHECK_MACROS: list[Macro] = [
    Macro(
        name="Basic check",
        description=(
            "Checks who has root access on this system, and whether a "
            "firewall is guarding it. Parses /etc/passwd and /etc/group "
            "directly (zero dependency, world-readable) to find UID-0 "
            "accounts and members of privileged groups (sudo/wheel/admin/"
            "root), then best-effort reads /etc/sudoers and "
            "/etc/sudoers.d for explicit per-user grants -- unreadable "
            "without elevated privileges unless its sudo option is "
            "enabled. Also detects whichever firewall frontend is "
            "installed (ufw/firewalld/nftables/iptables) and reports "
            "whether it's active, enabled at boot, and -- with its own "
            "separate sudo option -- its default incoming policy, "
            "port-80 rate-limiting, and allowed inbound ports (this half "
            "can also be re-run on its own as 'Basic Firewall Check', "
            "just below). Press → on this macro to configure which rows "
            "to show and which of the two sudo options to enable."
        ),
        steps=BASIC_CHECK_STEPS,
        options=BASIC_CHECK_OPTIONS,
        run=basic_check,
    ),
    FIREWALL_CHECK,
]
