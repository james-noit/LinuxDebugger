"""Logs-panel macros."""

import os
import re

from .common import Macro, MacroResult, MacroRun, RawLog, StatusItem, UNKNOWN, which

PSEUDO_FS_TYPES = {
    "proc", "sysfs", "tmpfs", "devtmpfs", "devpts", "cgroup", "cgroup2",
    "overlay", "squashfs", "autofs", "mqueue", "debugfs", "tracefs",
    "securityfs", "pstore", "bpf", "configfs", "fusectl", "hugetlbfs",
    "binfmt_misc", "rpc_pipefs", "efivarfs", "nsfs",
}


def _level_for_percent(percent: float, warn_at: float = 70, crit_at: float = 90) -> str:
    if percent >= crit_at:
        return "crit"
    if percent >= warn_at:
        return "warn"
    return "ok"


# -- System health check ---------------------------------------------------

SYSTEM_HEALTH_STEPS: tuple[tuple[str, ...], ...] = (
    ("systemctl", "--failed", "--no-legend"),
    ("journalctl", "-p", "err", "-b", "-q", "-o", "cat"),
    ("read", "/proc/loadavg"),
    ("read", "statvfs('/')"),
)


async def system_health_check() -> MacroRun:
    log = RawLog()
    items: list[StatusItem] = []

    if which("systemctl"):
        output = await log.probe(("systemctl", "--failed", "--no-legend"))
        if output is not None:
            failed = [line for line in output.splitlines() if line.strip()]
            count = len(failed)
            items.append(
                StatusItem(
                    "Failed systemd units",
                    f"{count} failed" if count else "none",
                    level="crit" if count else "ok",
                )
            )
        else:
            items.append(StatusItem("Failed systemd units", "unavailable", level="unknown"))
    else:
        items.append(StatusItem("Failed systemd units", "systemctl not installed", level="unknown"))

    if which("journalctl"):
        output = await log.probe(("journalctl", "-p", "err", "-b", "-q", "-o", "cat"))
        if output is not None:
            count = len([line for line in output.splitlines() if line.strip()])
            items.append(
                StatusItem(
                    "Errors logged since boot",
                    f"{count} error-level lines",
                    level="crit" if count > 10 else ("warn" if count else "ok"),
                )
            )
        else:
            items.append(
                StatusItem(
                    "Errors logged since boot",
                    "unavailable (permission denied or no journal)",
                    level="unknown",
                )
            )
    else:
        items.append(
            StatusItem("Errors logged since boot", "journalctl not installed", level="unknown")
        )

    try:
        with open("/proc/loadavg") as f:
            load1 = float(f.read().split()[0])
        cores = os.cpu_count() or 1
        log.note("read /proc/loadavg", f"{load1} (cores={cores})")
        ratio = load1 / cores
        items.append(
            StatusItem(
                "Load average (1 min)",
                f"{load1:.2f} across {cores} cores",
                level="crit" if ratio > 2 else ("warn" if ratio > 1 else "ok"),
            )
        )
    except OSError:
        log.note("read /proc/loadavg", "(not available)")
        items.append(StatusItem("Load average (1 min)", "unavailable", level="unknown"))

    try:
        stats = os.statvfs("/")
        used_pct = (1 - stats.f_bavail / stats.f_blocks) * 100 if stats.f_blocks else 0.0
        log.note("read statvfs('/')", f"{used_pct:.1f}% used")
        items.append(
            StatusItem(
                "Root filesystem usage",
                f"{used_pct:.1f}% used",
                level=_level_for_percent(used_pct, warn_at=80, crit_at=95),
            )
        )
    except OSError:
        log.note("read statvfs('/')", "(not available)")
        items.append(StatusItem("Root filesystem usage", "unavailable", level="unknown"))

    result = MacroResult(title="System Health Check", items=items, kind="semaphore")
    return MacroRun(result=result, raw_log=log.text())


# -- Memory pressure check --------------------------------------------------

MEMORY_PRESSURE_STEPS: tuple[tuple[str, ...], ...] = (
    ("read", "/proc/meminfo"),
    ("journalctl", "-k", "-b", "-g", "Out of memory|oom-kill|Killed process", "-q", "-o", "cat"),
    ("dmesg", "-T"),
)


def _parse_meminfo() -> dict[str, int]:
    values: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                match = re.match(r"^(\w+):\s+(\d+)\s*kB", line)
                if match:
                    values[match.group(1)] = int(match.group(2))
    except OSError:
        pass
    return values


async def memory_pressure_check() -> MacroRun:
    log = RawLog()
    items: list[StatusItem] = []

    meminfo = _parse_meminfo()
    log.note("read /proc/meminfo", "\n".join(f"{k}: {v} kB" for k, v in meminfo.items()) or "(unavailable)")

    total = meminfo.get("MemTotal")
    available = meminfo.get("MemAvailable")
    if total and available is not None:
        used_pct = (1 - available / total) * 100
        items.append(
            StatusItem(
                "RAM used",
                f"{(total - available) / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} GiB",
                percent=used_pct,
                level=_level_for_percent(used_pct),
            )
        )
    else:
        items.append(StatusItem("RAM used", "unavailable", level="unknown"))

    swap_total = meminfo.get("SwapTotal")
    swap_free = meminfo.get("SwapFree")
    if swap_total:
        swap_used_pct = (1 - swap_free / swap_total) * 100 if swap_free is not None else 0.0
        items.append(
            StatusItem(
                "Swap used",
                f"{(swap_total - (swap_free or 0)) / 1024 / 1024:.1f} / {swap_total / 1024 / 1024:.1f} GiB",
                percent=swap_used_pct,
                level=_level_for_percent(swap_used_pct, warn_at=50, crit_at=85),
            )
        )
    else:
        items.append(StatusItem("Swap used", "no swap configured", level="neutral"))

    oom_pattern = r"Out of memory|oom-kill|Killed process"
    output: str | None = None
    if which("journalctl"):
        output = await log.probe(
            ("journalctl", "-k", "-b", "-g", oom_pattern, "-q", "-o", "cat"), grep=True
        )
    if output is None and which("dmesg"):
        output = await log.probe(("dmesg", "-T"))
        if output is not None:
            output = "\n".join(
                line for line in output.splitlines() if re.search(oom_pattern, line, re.IGNORECASE)
            )

    if output is None:
        items.append(StatusItem("OOM kills (recent)", "unavailable", level="unknown", percent=None))
    else:
        count = len([line for line in output.splitlines() if line.strip()])
        items.append(
            StatusItem(
                "OOM kills (recent)",
                f"{count} found" if count else "none found",
                level="crit" if count else "ok",
                percent=None,
            )
        )

    result = MacroResult(title="Memory Pressure Check", items=items, kind="gauge")
    return MacroRun(result=result, raw_log=log.text())


# -- Disk space diagnosis ---------------------------------------------------

DISK_SPACE_STEPS: tuple[tuple[str, ...], ...] = (
    ("read", "/proc/mounts"),
    ("read", "statvfs(<each real mount>)"),
)


def _real_mounts() -> list[tuple[str, str]]:
    mounts: list[tuple[str, str]] = []
    seen_devices: set[str] = set()
    try:
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                device, mountpoint, fstype = parts[0], parts[1], parts[2]
                if fstype in PSEUDO_FS_TYPES or not device.startswith("/"):
                    continue
                if device in seen_devices:
                    continue
                seen_devices.add(device)
                mounts.append((mountpoint, fstype))
    except OSError:
        pass
    return mounts


async def disk_space_diagnosis() -> MacroRun:
    log = RawLog()
    mounts = _real_mounts()
    log.note("read /proc/mounts", "\n".join(f"{mp} ({fs})" for mp, fs in mounts) or "(none found)")

    items: list[StatusItem] = []
    if not mounts:
        items.append(StatusItem("Mounted filesystems", "none found", level="unknown"))
    for mountpoint, fstype in mounts[:8]:
        try:
            stats = os.statvfs(mountpoint)
            used_pct = (1 - stats.f_bavail / stats.f_blocks) * 100 if stats.f_blocks else 0.0
            free_gib = stats.f_bavail * stats.f_frsize / (1024 ** 3)
            inode_pct = (
                (1 - stats.f_favail / stats.f_files) * 100 if stats.f_files else 0.0
            )
            log.note(
                f"statvfs({mountpoint!r})",
                f"used={used_pct:.1f}% free={free_gib:.1f}GiB inodes={inode_pct:.1f}%",
            )
            items.append(
                StatusItem(
                    f"{mountpoint} ({fstype})",
                    f"{used_pct:.1f}% used, {free_gib:.1f} GiB free, {inode_pct:.1f}% inodes used",
                )
            )
        except OSError:
            log.note(f"statvfs({mountpoint!r})", "(not available)")

    if not items:
        items.append(StatusItem("Mounted filesystems", "unavailable", level="unknown"))

    result = MacroResult(title="Disk Space Diagnosis", items=items, kind="fields")
    return MacroRun(result=result, raw_log=log.text())


# -- Boot time report --------------------------------------------------

BOOT_TIME_STEPS: tuple[tuple[str, ...], ...] = (
    ("read", "/proc/uptime"),
    ("systemd-analyze",),
    ("systemd-analyze", "blame"),
)


def _format_duration(seconds: float) -> str:
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


async def boot_time_report() -> MacroRun:
    log = RawLog()
    items: list[StatusItem] = []

    try:
        with open("/proc/uptime") as f:
            uptime_seconds = float(f.read().split()[0])
        log.note("read /proc/uptime", f"{uptime_seconds:.0f}s")
        items.append(StatusItem("System uptime", _format_duration(uptime_seconds)))
    except OSError:
        log.note("read /proc/uptime", "(not available)")
        items.append(StatusItem("System uptime", "unavailable", level="unknown"))

    if which("systemd-analyze"):
        output = await log.probe(("systemd-analyze",))
        items.append(StatusItem("Boot analysis", output.strip() if output else "unavailable"))

        blame_output = await log.probe(("systemd-analyze", "blame"))
        if blame_output:
            top = [line.strip() for line in blame_output.splitlines()[:5] if line.strip()]
            items.append(StatusItem("Slowest services", "; ".join(top) if top else "none"))
    else:
        items.append(StatusItem("Boot analysis", "systemd-analyze not installed", level="unknown"))

    result = MacroResult(title="Boot Time Report", items=items, kind="fields")
    return MacroRun(result=result, raw_log=log.text())


LOG_MACROS: list[Macro] = [
    Macro(
        name="System health check",
        description=(
            "Four independent checks reduced to a semaphore: failed "
            "systemd units, error-level log lines since boot, 1-minute "
            "load average against CPU core count, and root filesystem "
            "usage (via os.statvfs, zero dependency). Each dot is green/"
            "yellow/red on its own thresholds, unknown/grey if the "
            "underlying tool isn't installed or permission was denied."
        ),
        steps=SYSTEM_HEALTH_STEPS,
        run=system_health_check,
    ),
    Macro(
        name="Memory pressure check",
        description=(
            "Reads /proc/meminfo directly (zero dependency) for RAM and "
            "swap usage, shown as gauges, then checks journalctl/dmesg for "
            "OOM-killer activity -- answers 'is something getting killed "
            "for memory' in one shot."
        ),
        steps=MEMORY_PRESSURE_STEPS,
        run=memory_pressure_check,
    ),
    Macro(
        name="Disk space diagnosis",
        description=(
            "Reads /proc/mounts for every real (non-pseudo) filesystem and "
            "os.statvfs each one directly -- entirely zero-dependency, no "
            "`df` needed -- reporting used space, free space, AND inode "
            "usage per mount, since a filesystem can run out of inodes "
            "while space-based tools still show plenty free."
        ),
        steps=DISK_SPACE_STEPS,
        run=disk_space_diagnosis,
    ),
    Macro(
        name="Boot time report",
        description=(
            "System uptime from /proc/uptime (zero dependency), plus a "
            "systemd-analyze boot time breakdown and its slowest services "
            "if systemd-analyze is installed."
        ),
        steps=BOOT_TIME_STEPS,
        run=boot_time_report,
    ),
]
