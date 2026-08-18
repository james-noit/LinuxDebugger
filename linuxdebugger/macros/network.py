"""Network-panel macros."""

import asyncio
import re
import socket
import struct

from .common import Macro, MacroResult, MacroRun, RawLog, StatusItem, UNKNOWN, which


def _default_route() -> tuple[str, str] | None:
    """Pure /proc/net/route parse -- zero dependency, no `ip`/`route`
    needed. Returns (gateway_ip, interface) or None."""
    try:
        with open("/proc/net/route") as f:
            lines = f.readlines()[1:]
    except OSError:
        return None
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        iface, dest, gateway = parts[0], parts[1], parts[2]
        if dest == "00000000" and gateway != "00000000":
            try:
                gw_ip = socket.inet_ntoa(struct.pack("<L", int(gateway, 16)))
            except (ValueError, OSError):
                continue
            return gw_ip, iface
    return None


async def _resolve(host: str, timeout: float = 3.0) -> str | None:
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, socket.gethostbyname, host), timeout
        )
    except (socket.gaierror, OSError, asyncio.TimeoutError):
        return None


async def _ping_ok(log: RawLog, host: str) -> bool | None:
    """Returns True/False if ping ran, None if ping isn't installed."""
    if not which("ping"):
        log.note(f"ping -c 1 -W 2 {host}", "(ping not installed)")
        return None
    output = await log.probe(("ping", "-c", "1", "-W", "2", host))
    return output is not None


# -- Connectivity ladder -----------------------------------------------

CONNECTIVITY_STEPS: tuple[tuple[str, ...], ...] = (
    ("read", "/proc/net/route"),
    ("ping", "-c", "1", "-W", "2", "<gateway>"),
    ("ping", "-c", "1", "-W", "2", "1.1.1.1"),
    ("resolve", "example.com"),
)


async def connectivity_ladder() -> MacroRun:
    log = RawLog()
    items: list[StatusItem] = []

    route = _default_route()
    if route is None:
        log.note("read /proc/net/route", "(no default route found)")
        items.append(StatusItem("Default route", "none found", level="crit"))
        for label in ("Gateway reachable", "Internet reachable", "DNS resolution"):
            items.append(StatusItem(label, "skipped (no route)", level="unknown"))
        return MacroRun(
            result=MacroResult(title="Connectivity Ladder", items=items, kind="ladder"),
            raw_log=log.text(),
        )

    gateway_ip, iface = route
    log.note("read /proc/net/route", f"default via {gateway_ip} dev {iface}")
    items.append(StatusItem("Default route", f"via {gateway_ip} on {iface}", level="ok"))

    gateway_ok = await _ping_ok(log, gateway_ip)
    if gateway_ok is None:
        items.append(StatusItem("Gateway reachable", "ping not installed, skipping check", level="unknown"))
    elif gateway_ok:
        items.append(StatusItem("Gateway reachable", f"{gateway_ip} responded", level="ok"))
    else:
        items.append(StatusItem("Gateway reachable", f"{gateway_ip} did not respond", level="crit"))

    if gateway_ok is False:
        items.append(StatusItem("Internet reachable", "skipped (gateway unreachable)", level="unknown"))
        items.append(StatusItem("DNS resolution", "skipped (gateway unreachable)", level="unknown"))
        return MacroRun(
            result=MacroResult(title="Connectivity Ladder", items=items, kind="ladder"),
            raw_log=log.text(),
        )

    internet_ok = await _ping_ok(log, "1.1.1.1")
    if internet_ok is None:
        items.append(StatusItem("Internet reachable", "ping not installed, skipping check", level="unknown"))
    elif internet_ok:
        items.append(StatusItem("Internet reachable", "1.1.1.1 responded", level="ok"))
    else:
        items.append(StatusItem("Internet reachable", "1.1.1.1 did not respond", level="crit"))

    if internet_ok is False:
        items.append(StatusItem("DNS resolution", "skipped (internet unreachable)", level="unknown"))
        return MacroRun(
            result=MacroResult(title="Connectivity Ladder", items=items, kind="ladder"),
            raw_log=log.text(),
        )

    resolved = await _resolve("example.com")
    log.note("resolve example.com", resolved or "(resolution failed)")
    if resolved:
        items.append(StatusItem("DNS resolution", f"example.com -> {resolved}", level="ok"))
    else:
        items.append(StatusItem("DNS resolution", "example.com did not resolve", level="crit"))

    result = MacroResult(title="Connectivity Ladder", items=items, kind="ladder")
    return MacroRun(result=result, raw_log=log.text())


# -- DNS check -----------------------------------------------------------

DNS_CHECK_STEPS: tuple[tuple[str, ...], ...] = (
    ("read", "/etc/resolv.conf"),
    ("dig", "@<server>", "example.com", "+short", "+time=2", "+tries=1"),
    ("resolve", "example.com"),
)


def _parse_resolv_conf() -> list[str]:
    servers: list[str] = []
    try:
        with open("/etc/resolv.conf") as f:
            for line in f:
                match = re.match(r"^\s*nameserver\s+(\S+)", line)
                if match:
                    servers.append(match.group(1))
    except OSError:
        pass
    return servers


async def dns_check() -> MacroRun:
    log = RawLog()
    items: list[StatusItem] = []

    servers = _parse_resolv_conf()
    log.note("read /etc/resolv.conf", "\n".join(servers) if servers else "(no nameserver lines found)")
    if servers:
        items.append(StatusItem("Configured resolvers", ", ".join(servers), level="neutral"))
    else:
        items.append(StatusItem("Configured resolvers", "none found in /etc/resolv.conf", level="warn"))

    if servers and which("dig"):
        for server in servers[:3]:
            output = await log.probe(("dig", f"@{server}", "example.com", "+short", "+time=2", "+tries=1"))
            ok = bool(output and output.strip())
            items.append(
                StatusItem(
                    f"Resolver {server}",
                    "responded" if ok else "no response",
                    level="ok" if ok else "crit",
                )
            )
    else:
        if servers:
            log.note("dig", "(not installed -- falling back to the system resolver)")
        resolved = await _resolve("example.com")
        log.note("resolve example.com", resolved or "(resolution failed)")
        items.append(
            StatusItem(
                "System resolver",
                f"example.com -> {resolved}" if resolved else "resolution failed",
                level="ok" if resolved else "crit",
            )
        )

    result = MacroResult(title="DNS Check", items=items, kind="semaphore")
    return MacroRun(result=result, raw_log=log.text())


# -- Listening services summary ------------------------------------------

LISTENING_SERVICES_STEPS: tuple[tuple[str, ...], ...] = (("ss", "-tulpn"),)

_SS_PROC_RE = re.compile(r'users:\(\("([^"]+)"')


def _parse_ss(output: str) -> list[tuple[str, str, str]]:
    # A single port often has multiple actual listening sockets (IPv4 +
    # IPv6, or several bound addresses) -- collapse those into one row per
    # (proto, port) instead of showing the same port repeatedly.
    procs_by_key: dict[tuple[str, str], set[str]] = {}
    order: list[tuple[str, str]] = []
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        proto = parts[0]
        local = parts[4]
        port = local.rsplit(":", 1)[-1]
        key = (proto, port)
        if key not in procs_by_key:
            procs_by_key[key] = set()
            order.append(key)
        proc_match = _SS_PROC_RE.search(line)
        if proc_match:
            procs_by_key[key].add(proc_match.group(1))

    rows: list[tuple[str, str, str]] = []
    for proto, port in order:
        procs = procs_by_key[(proto, port)]
        rows.append((proto, port, ", ".join(sorted(procs)) if procs else "?"))
    return rows


async def listening_services_summary() -> MacroRun:
    log = RawLog()
    items: list[StatusItem] = []

    if not which("ss"):
        log.note("ss -tulpn", "(not installed)")
        items.append(StatusItem("Listening ports", "ss not installed", level="unknown"))
        return MacroRun(
            result=MacroResult(title="Listening Services", items=items, kind="fields"),
            raw_log=log.text(),
        )

    output = await log.probe(("ss", "-tulpn"))
    rows = _parse_ss(output) if output else []

    def _port_key(row: tuple[str, str, str]) -> int:
        try:
            return int(row[1])
        except ValueError:
            return 0

    rows.sort(key=_port_key)
    items.append(StatusItem("Listening ports found", str(len(rows))))
    for proto, port, proc in rows[:12]:
        items.append(StatusItem(f"{proto}/{port}", proc))
    if len(rows) > 12:
        items.append(StatusItem("...", f"{len(rows) - 12} more not shown"))

    result = MacroResult(title="Listening Services", items=items, kind="fields")
    return MacroRun(result=result, raw_log=log.text())


# -- Wi-Fi diagnosis --------------------------------------------------------

WIFI_DIAGNOSIS_STEPS: tuple[tuple[str, ...], ...] = (
    ("nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"),
    ("nmcli", "-t", "-f", "active,ssid,signal", "dev", "wifi"),
    ("read", "/sys/class/net/*/wireless"),
)


async def wifi_diagnosis() -> MacroRun:
    log = RawLog()
    items: list[StatusItem] = []

    if not which("nmcli"):
        log.note("nmcli", "(not installed)")
        from pathlib import Path

        wireless_ifaces = [p.parent.parent.name for p in Path("/sys/class/net").glob("*/wireless")]
        log.note("read /sys/class/net/*/wireless", ", ".join(wireless_ifaces) or "(none found)")
        items.append(
            StatusItem(
                "Wireless interface",
                ", ".join(wireless_ifaces) if wireless_ifaces else "none found",
                level="neutral" if wireless_ifaces else "unknown",
            )
        )
        items.append(StatusItem("Connection state", "nmcli not installed, cannot query", level="unknown"))
        result = MacroResult(title="Wi-Fi Diagnosis", items=items, kind="fields")
        return MacroRun(result=result, raw_log=log.text())

    status_output = await log.probe(("nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"))
    wifi_device = None
    wifi_state = UNKNOWN
    if status_output:
        for line in status_output.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[1] == "wifi":
                wifi_device, wifi_state = parts[0], parts[2]
                break
    items.append(StatusItem("Wireless interface", wifi_device or "none found"))
    items.append(StatusItem("Connection state", wifi_state))

    wifi_output = await log.probe(("nmcli", "-t", "-f", "active,ssid,signal", "dev", "wifi"))
    ssid = "not connected"
    signal = UNKNOWN
    if wifi_output:
        for line in wifi_output.splitlines():
            parts = line.split(":")
            if len(parts) >= 3 and parts[0] == "yes":
                ssid, signal = parts[1], parts[2]
                break
    items.append(StatusItem("Connected SSID", ssid))
    items.append(StatusItem("Signal strength", f"{signal}%" if signal != UNKNOWN else UNKNOWN))

    result = MacroResult(title="Wi-Fi Diagnosis", items=items, kind="fields")
    return MacroRun(result=result, raw_log=log.text())


NETWORK_MACROS: list[Macro] = [
    Macro(
        name="Connectivity ladder",
        description=(
            "Walks the classic layered check as a decision tree: default "
            "route (from /proc/net/route, zero dependency) -> gateway "
            "ping -> internet ping -> DNS resolution. Each rung only runs "
            "if the previous one succeeded, so the result points at "
            "exactly which layer is broken instead of a wall of raw "
            "output."
        ),
        steps=CONNECTIVITY_STEPS,
        run=connectivity_ladder,
    ),
    Macro(
        name="DNS check",
        description=(
            "Reads /etc/resolv.conf directly (zero dependency) for "
            "configured resolvers, then tests each one individually with "
            "`dig` if installed, falling back to a single system-resolver "
            "lookup via Python's own socket module otherwise."
        ),
        steps=DNS_CHECK_STEPS,
        run=dns_check,
    ),
    Macro(
        name="Listening services summary",
        description=(
            "Runs `ss -tulpn` and reduces it to a port -> process table, "
            "good for a quick 'what's already using this port' or "
            "exposure check."
        ),
        steps=LISTENING_SERVICES_STEPS,
        run=listening_services_summary,
    ),
    Macro(
        name="Wi-Fi diagnosis",
        description=(
            "Uses nmcli to report the wireless device's state, connected "
            "SSID and signal strength if NetworkManager is in use; falls "
            "back to checking for a wireless interface directly via sysfs "
            "if nmcli isn't installed."
        ),
        steps=WIFI_DIAGNOSIS_STEPS,
        run=wifi_diagnosis,
    ),
]
