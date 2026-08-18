"""Firewall check macro for the System Check panel.

Distro-agnostic: detects whichever firewall frontend is actually present
(ufw / firewalld / nft / iptables, checked in that preference order) rather
than assuming one distro's tooling. Read-only throughout -- it only ever
reports what it finds, it never enables, configures, or changes firewall
policy.
"""

import re

from .common import UNKNOWN, Macro, MacroOption, MacroResult, MacroRun, RawLog, StatusItem, which

# Preference order: friendliest / most common frontend first. A system can
# have iptables binaries present even though ufw or firewalld is actually
# in charge, so checking in this order avoids misidentifying which one is
# actually managing the firewall.
_BACKENDS = ("ufw", "firewalld", "nft", "iptables")

# Not every backend has a single, consistent systemd unit across distros
# (iptables notably doesn't) -- missing here means "not applicable", not
# "inactive".
_SYSTEMD_UNIT = {"ufw": "ufw", "firewalld": "firewalld", "nft": "nftables"}

_REFERENCE_PORTS = (
    ("22", "SSH"),
    ("80", "HTTP"),
    ("443", "HTTPS"),
    ("143", "IMAP"),
    ("993", "IMAPS"),
    ("110", "POP3"),
)

_SERVICE_PORTS = {"ssh": "22", "http": "80", "https": "443", "imap": "143", "imaps": "993", "pop3": "110"}

_ACTIVE_LEVELS = {"active": "ok", "inactive": "crit", "failed": "crit", "activating": "warn", "deactivating": "warn"}
_ENABLED_LEVELS = {"enabled": "ok", "enabled-runtime": "ok", "disabled": "warn", "static": "neutral", "masked": "warn", "alias": "neutral"}
_POLICY_LEVEL = {"deny": "ok", "reject": "ok", "allow": "crit"}

_PORT_TOKEN_RE = re.compile(r"^(\d{1,5})(?:/(?:tcp|udp))?\b")


def _detect_backend() -> str | None:
    for name in _BACKENDS:
        binary = "firewall-cmd" if name == "firewalld" else name
        if which(binary):
            return name
    return None


async def _service_state(log: RawLog, backend: str, query: str) -> str:
    unit = _SYSTEMD_UNIT.get(backend)
    if unit is None:
        log.note(f"systemctl {query} ({backend})", "(no consistent systemd unit for this backend)")
        return UNKNOWN
    output = await log.probe(("systemctl", query, unit), grep=True)
    if not output:
        return UNKNOWN
    return output.strip().splitlines()[0].strip()


async def _read_ufw_rules(log: RawLog, password: str | None) -> dict | None:
    output = await log.probe_sudo(("ufw", "status", "verbose"), password)
    if output is None:
        return None
    policy = None
    dos_limit_80 = False
    allowed_ports: set[str] = set()
    for line in output.splitlines():
        stripped = line.strip()
        match = re.match(r"Default:\s*(\w+)\s*\(incoming\)", stripped)
        if match:
            policy = match.group(1).lower()
            continue
        match = _PORT_TOKEN_RE.match(stripped)
        if match and ("ALLOW" in stripped or "LIMIT" in stripped):
            port = match.group(1)
            allowed_ports.add(port)
            if port == "80" and "LIMIT" in stripped:
                dos_limit_80 = True
    return {"policy": policy, "dos_limit_80": dos_limit_80, "allowed_ports": allowed_ports}


async def _read_firewalld_rules(log: RawLog, password: str | None) -> dict | None:
    output = await log.probe_sudo(("firewall-cmd", "--list-all"), password)
    if output is None:
        return None
    policy = None
    dos_limit_80 = False
    allowed_ports: set[str] = set()
    for line in output.splitlines():
        stripped = line.strip()
        match = re.match(r"target:\s*(\S+)", stripped)
        if match:
            target = match.group(1).strip("%").upper()
            policy = {"DROP": "deny", "REJECT": "reject", "ACCEPT": "allow", "DEFAULT": "deny"}.get(target, target.lower())
            continue
        if stripped.startswith("services:"):
            for name in stripped.removeprefix("services:").split():
                if name in _SERVICE_PORTS:
                    allowed_ports.add(_SERVICE_PORTS[name])
            continue
        if stripped.startswith("ports:"):
            for token in stripped.removeprefix("ports:").split():
                match = _PORT_TOKEN_RE.match(token)
                if match:
                    allowed_ports.add(match.group(1))
            continue
        if "port=" in stripped and "80" in stripped and "limit" in stripped:
            dos_limit_80 = True
    return {"policy": policy, "dos_limit_80": dos_limit_80, "allowed_ports": allowed_ports}


async def _read_nft_rules(log: RawLog, password: str | None) -> dict | None:
    output = await log.probe_sudo(("nft", "list", "ruleset"), password)
    if output is None:
        return None
    policy = None
    dos_limit_80 = False
    allowed_ports: set[str] = set()
    in_input_chain = False
    for line in output.splitlines():
        stripped = line.strip()
        if re.match(r"chain input\b", stripped, re.IGNORECASE):
            in_input_chain = True
        elif stripped.startswith("chain "):
            in_input_chain = False
        match = re.search(r"policy (drop|reject|accept)", stripped)
        if match and in_input_chain:
            policy = {"drop": "deny", "reject": "reject", "accept": "allow"}[match.group(1)]
        for port_match in re.finditer(r"dport\s*\{?\s*([\d,\s]+)\}?", stripped):
            for port in port_match.group(1).replace(" ", "").split(","):
                if port.isdigit():
                    allowed_ports.add(port)
        if "dport 80" in stripped and "limit rate" in stripped:
            dos_limit_80 = True
    return {"policy": policy, "dos_limit_80": dos_limit_80, "allowed_ports": allowed_ports}


async def _read_iptables_rules(log: RawLog, password: str | None) -> dict | None:
    output = await log.probe_sudo(("iptables", "-L", "INPUT", "-n", "-v"), password)
    if output is None:
        return None
    policy = None
    dos_limit_80 = False
    allowed_ports: set[str] = set()
    for line in output.splitlines():
        match = re.match(r"Chain INPUT \(policy (\w+)", line)
        if match:
            policy = {"DROP": "deny", "REJECT": "reject", "ACCEPT": "allow"}.get(match.group(1).upper(), match.group(1).lower())
            continue
        if "ACCEPT" in line:
            match = re.search(r"dpt:(\d+)", line)
            if match:
                allowed_ports.add(match.group(1))
        if "dpt:80" in line and "limit" in line.lower():
            dos_limit_80 = True
    return {"policy": policy, "dos_limit_80": dos_limit_80, "allowed_ports": allowed_ports}


_RULE_READERS = {
    "ufw": _read_ufw_rules,
    "firewalld": _read_firewalld_rules,
    "nft": _read_nft_rules,
    "iptables": _read_iptables_rules,
}


async def _read_rules(log: RawLog, backend: str, use_sudo: bool, password: str | None) -> dict | None:
    if not use_sudo:
        log.note("read firewall rules", "(skipped -- 'Require sudo to read firewall rules' not enabled)")
        return None
    return await _RULE_READERS[backend](log, password)


FIREWALL_CHECK_STEPS: tuple[tuple[str, ...], ...] = (
    ("which", "ufw", "firewall-cmd", "nft", "iptables"),
    ("systemctl", "is-active", "<detected firewall unit>"),
    ("systemctl", "is-enabled", "<detected firewall unit>"),
    ("sudo", "<detected firewall tool>", "<status/list-rules>"),
)

# Same two kinds of option as Basic check: one privilege toggle (off by
# default) gating the three rows that need root to determine, and a "show"
# toggle per output row (on by default).
FIREWALL_CHECK_OPTIONS: tuple[MacroOption, ...] = (
    MacroOption(
        key="sudo_rules",
        label="Require sudo to read firewall rules",
        description=(
            "Prompts for your sudo password and reads the active ruleset "
            "as root to determine the default incoming policy, whether "
            "port 80 has basic rate-limiting, and which reference ports "
            "are explicitly allowed. Without this, those three rows "
            "report unknown -- reading firewall rules needs root on "
            "every backend (ufw/firewalld/nftables/iptables). The "
            "password is used only for this run and is not stored."
        ),
        default=False,
        requires_sudo=True,
    ),
    MacroOption(
        key="show_tool",
        label="Show: Firewall tool detected",
        description="Which firewall frontend (ufw/firewalld/nftables/iptables) is installed, if any.",
        default=True,
    ),
    MacroOption(
        key="show_active",
        label="Show: Firewall service active",
        description="Whether the detected firewall's systemd service is currently running.",
        default=True,
    ),
    MacroOption(
        key="show_enabled",
        label="Show: Firewall enabled at boot",
        description="Whether the detected firewall's systemd service is enabled to start at boot.",
        default=True,
    ),
    MacroOption(
        key="show_policy",
        label="Show: Firewall default incoming policy",
        description="Whether the firewall's default policy for incoming traffic is deny/reject or allow.",
        default=True,
    ),
    MacroOption(
        key="show_dos_limit",
        label="Show: Firewall DoS mitigation (port 80)",
        description="Whether a rate-limiting rule is present for port 80. Informational, not a pass/fail.",
        default=True,
    ),
    MacroOption(
        key="show_ports",
        label="Show: Firewall allowed inbound ports",
        description="Which of SSH/HTTP/HTTPS/IMAP/IMAPS/POP3 are explicitly allowed. Informational, not a pass/fail.",
        default=True,
    ),
)


async def collect_firewall_items(
    log: RawLog,
    *,
    want_tool: bool,
    want_active: bool,
    want_enabled: bool,
    want_policy: bool,
    want_dos_limit: bool,
    want_ports: bool,
    use_sudo: bool,
    password: str | None,
) -> list[StatusItem]:
    """The shared firewall probe/render logic, reused by both the
    standalone 'Basic Firewall Check' macro and the firewall section
    folded into 'Basic check'. Split out so the two call sites can pick
    an independent subset of rows without duplicating any probing or
    parsing code."""
    items: list[StatusItem] = []

    backend = _detect_backend()
    log.note(
        "detect firewall frontend",
        backend or "none of ufw/firewall-cmd/nft/iptables found on PATH",
    )
    if want_tool:
        items.append(
            StatusItem(
                "Firewall tool detected",
                backend if backend else "none found",
                level="ok" if backend else "crit",
            )
        )

    if backend is None:
        return items

    if want_active:
        active = await _service_state(log, backend, "is-active")
        items.append(StatusItem("Firewall service active", active, level=_ACTIVE_LEVELS.get(active, "unknown")))

    if want_enabled:
        enabled = await _service_state(log, backend, "is-enabled")
        items.append(StatusItem("Firewall enabled at boot", enabled, level=_ENABLED_LEVELS.get(enabled, "unknown")))

    rules = await _read_rules(log, backend, use_sudo, password) if (want_policy or want_dos_limit or want_ports) else None

    if want_policy:
        if rules is None:
            items.append(
                StatusItem(
                    "Firewall default incoming policy",
                    "unknown (enable 'Require sudo to read firewall rules')",
                    level="unknown",
                )
            )
        else:
            policy = rules.get("policy")
            items.append(
                StatusItem(
                    "Firewall default incoming policy",
                    policy or "unparseable",
                    level=_POLICY_LEVEL.get(policy, "unknown"),
                )
            )

    if want_dos_limit:
        if rules is None:
            items.append(
                StatusItem(
                    "Firewall DoS mitigation (port 80)",
                    "unknown (enable 'Require sudo to read firewall rules')",
                    level="unknown",
                )
            )
        else:
            has_limit = rules.get("dos_limit_80")
            items.append(
                StatusItem(
                    "Firewall DoS mitigation (port 80)",
                    "rate-limit rule present" if has_limit else "no rate-limit rule found",
                    level="neutral",
                )
            )

    if want_ports:
        if rules is None:
            items.append(
                StatusItem(
                    "Firewall allowed inbound ports",
                    "unknown (enable 'Require sudo to read firewall rules')",
                    level="unknown",
                )
            )
        else:
            allowed = rules.get("allowed_ports", set())
            described = [f"{port}/{name}" for port, name in _REFERENCE_PORTS if port in allowed]
            extra = sorted(allowed - {port for port, _name in _REFERENCE_PORTS})
            parts = described + ([f"+{len(extra)} other port(s)"] if extra else [])
            items.append(
                StatusItem(
                    "Firewall allowed inbound ports",
                    ", ".join(parts) if parts else "none of the reference ports found allowed",
                    level="neutral",
                )
            )

    return items


async def firewall_check(selected: frozenset[str] = frozenset(), password: str | None = None) -> MacroRun:
    log = RawLog()
    items = await collect_firewall_items(
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

    if not items:
        items.append(StatusItem("Nothing selected", "enable at least one 'Show:' option", level="unknown"))

    return MacroRun(
        result=MacroResult(title="Basic Firewall Check", items=items, kind="ladder"),
        raw_log=log.text(),
    )


FIREWALL_CHECK = Macro(
    name="Basic Firewall Check",
    description=(
        "The firewall half of Basic check, split out so it can be re-run "
        "on its own: checks whether a firewall is installed, active, and "
        "enabled on this system -- detecting whichever of ufw/firewalld/"
        "nftables/iptables is actually present rather than assuming one "
        "specific tool. Read-only: it never enables, configures, or "
        "changes firewall policy, it only reports what it finds. Press → "
        "on this macro to configure which rows to show and whether to "
        "elevate for reading the active ruleset (needed to see the "
        "default incoming policy, basic port-80 rate-limiting, and which "
        "reference ports are allowed)."
    ),
    steps=FIREWALL_CHECK_STEPS,
    options=FIREWALL_CHECK_OPTIONS,
    run=firewall_check,
    subordinate=True,
)
