from dataclasses import dataclass, field


@dataclass(frozen=True)
class Flag:
    """An optional flag that can be toggled on for a command."""

    tokens: tuple[str, ...]
    label: str
    description: str


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    base_args: tuple[str, ...] = ()
    requires_sudo: bool = False
    flags: tuple[Flag, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CommandPanel:
    name: str
    commands: list[Command]


LOG_COMMANDS: list[Command] = [
    Command(
        name="journalctl",
        description=(
            "The query tool for the systemd journal, the centralized, binary log "
            "store used by most modern distros (Debian, Ubuntu, Fedora, Arch, "
            "openSUSE, RHEL...). It merges kernel messages, service output and "
            "boot records into a single, structured, timestamped stream, and can "
            "filter by unit, priority, boot or time range. On most systems reading "
            "it requires being root or a member of the systemd-journal group."
        ),
        requires_sudo=True,
        flags=(
            Flag(
                ("-f",),
                "-f  follow",
                "Keep the journal open and print new entries as they are written, "
                "like `tail -f`. Ideal for watching what happens in real time while "
                "you reproduce a bug; the command only stops when you press Ctrl+K.",
            ),
            Flag(
                ("-xe",),
                "-xe  explain + jump to end",
                "Adds explanatory help text under journal messages that reference "
                "a documented message catalog (the '-x' part) and jumps straight "
                "to the end of the journal (the '-e' part), which is the fastest "
                "way to see what just went wrong after a crash or failed start.",
            ),
            Flag(
                ("-k",),
                "-k  kernel only",
                "Restricts the output to kernel messages only (the same data "
                "`dmesg` reads), letting you inspect driver, hardware and boot "
                "messages without the noise of every user-space service.",
            ),
            Flag(
                ("-b",),
                "-b  current boot",
                "Shows only the logs generated since the machine's current boot, "
                "which is usually what you want when debugging something that "
                "just happened rather than scrolling through days of history.",
            ),
            Flag(
                ("-p", "err"),
                "-p err  errors and worse",
                "Filters the output down to priority 'err' and above (err, crit, "
                "alert, emerg), hiding informational and warning noise so real "
                "failures stand out immediately.",
            ),
            Flag(
                ("--since", "today"),
                "--since today",
                "Shows only entries logged since midnight today, a quick way to "
                "cut out old history when you only care about what happened in "
                "the current session.",
            ),
        ),
    ),
    Command(
        name="dmesg",
        description=(
            "Prints the kernel ring buffer: the low-level log the kernel itself "
            "keeps for hardware detection, driver messages, filesystem errors, "
            "OOM-killer activity and other events that happen before or outside "
            "of systemd/syslog. Essential for diagnosing hardware, USB, disk or "
            "kernel-module problems. On most distros it needs root because the "
            "kernel restricts ring-buffer access by default (dmesg_restrict)."
        ),
        base_args=("--color=never",),
        requires_sudo=True,
        flags=(
            Flag(
                ("-w",),
                "-w  follow",
                "Waits for and prints new kernel messages as they arrive, the "
                "dmesg equivalent of `tail -f`. Useful while plugging in "
                "hardware or reproducing a driver crash live.",
            ),
            Flag(
                ("-l", "err,crit,alert,emerg"),
                "-l err+  errors and worse",
                "Filters kernel messages down to priority 'err' and above, "
                "hiding routine informational boot chatter so hardware and "
                "driver failures stand out.",
            ),
        ),
    ),
    Command(
        name="tail",
        description=(
            "Reads the end of a plain-text log file. Distros that still use "
            "traditional syslog-style logging (or that keep a text mirror of the "
            "journal) write to files under /var/log — which file matters depends "
            "on the distro family, so pick the flag matching yours. Root access "
            "is generally required because these files are only readable by the "
            "root user or the adm/log group."
        ),
        requires_sudo=True,
        flags=(
            Flag(
                ("-f", "/var/log/syslog"),
                "-f /var/log/syslog",
                "Follow the general system log used by Debian- and "
                "Ubuntu-based distros, which mirrors most non-kernel activity "
                "logged by services and daemons.",
            ),
            Flag(
                ("-f", "/var/log/messages"),
                "-f /var/log/messages",
                "Follow the general system log used by RHEL-, Fedora- and "
                "openSUSE-based distros, the equivalent of Debian's syslog on "
                "those families.",
            ),
            Flag(
                ("-f", "/var/log/auth.log"),
                "-f /var/log/auth.log",
                "Follow the authentication log used by Debian- and "
                "Ubuntu-based distros: logins, sudo usage, SSH attempts and "
                "other security-relevant events.",
            ),
            Flag(
                ("-f", "/var/log/secure"),
                "-f /var/log/secure",
                "Follow the authentication log used by RHEL-, Fedora- and "
                "openSUSE-based distros: logins, sudo usage, SSH attempts and "
                "other security-relevant events.",
            ),
        ),
    ),
    Command(
        name="last",
        description=(
            "Shows a history of user logins, logouts, and system reboots and "
            "shutdowns, read from /var/log/wtmp. Handy for confirming when a "
            "machine was rebooted, whether a login happened when it shouldn't "
            "have, or how long the system has been up between restarts."
        ),
        flags=(
            Flag(
                ("-x",),
                "-x  show shutdowns/reboots",
                "Also lists system shutdown and runlevel-change entries "
                "alongside user logins, so you can see reboots in the same "
                "timeline as who was logged in around them.",
            ),
        ),
    ),
    Command(
        name="who",
        description=(
            "Shows who is currently logged into the system, from which "
            "terminal, and since when. Useful for a quick check of active "
            "sessions on a shared or remote machine before making changes."
        ),
        flags=(
            Flag(
                ("-a",),
                "-a  all information",
                "Shows extra detail per session: idle time, process ID, the "
                "last system boot time, and the current runlevel, in addition "
                "to the basic user/terminal/login-time columns.",
            ),
        ),
    ),
    Command(
        name="systemctl",
        description=(
            "The main control command for systemd services (units). On its "
            "own it is used to start, stop and inspect services, but for "
            "debugging the most valuable view is the list of units that failed "
            "to start or crashed, which is exactly what the flag below shows."
        ),
        flags=(
            Flag(
                ("--failed",),
                "--failed  list failed units",
                "Lists every systemd unit currently in a 'failed' state — "
                "services that crashed, timed out, or could not start — which "
                "is usually the first place to look after a boot that feels "
                "wrong or a service that silently stopped working.",
            ),
        ),
    ),
    Command(
        name="uptime",
        description=(
            "Prints how long the system has been running, how many users are "
            "logged in, and the 1/5/15-minute load averages. A quick way to "
            "sanity-check whether a machine is under unusual load or was "
            "recently rebooted before diving into deeper log analysis."
        ),
    ),
    Command(
        name="free",
        description=(
            "Shows how much physical RAM and swap are in use, free, cached and "
            "available. Useful to rule out memory pressure or a swapping system "
            "before chasing a performance problem somewhere else."
        ),
        flags=(
            Flag(
                ("-h",),
                "-h  human-readable",
                "Prints sizes in KB/MB/GB instead of raw byte counts, which is "
                "much faster to read at a glance.",
            ),
        ),
    ),
    Command(
        name="df",
        description=(
            "Reports disk space usage per mounted filesystem. The first thing "
            "to check when a service refuses to write, logs stop rotating, or "
            "the disk is suspected to be full."
        ),
        flags=(
            Flag(
                ("-h",),
                "-h  human-readable",
                "Prints sizes in KB/MB/GB instead of raw 1K-block counts, which "
                "is much easier to scan quickly.",
            ),
        ),
    ),
    Command(
        name="ps",
        description=(
            "Lists running processes. With the flag below it shows every "
            "process on the system (not just the current terminal's), along "
            "with the user that owns it, CPU/memory usage, and the full "
            "command line — the standard first step when hunting a runaway "
            "or unexpected process."
        ),
        flags=(
            Flag(
                ("aux",),
                "aux  every process, full detail",
                "Shows all processes from all users, in the classic BSD-style "
                "long format with CPU%, memory% and the full command line for "
                "each one.",
            ),
        ),
    ),
    Command(
        name="vmstat",
        description=(
            "Reports a snapshot of processes, memory, paging, block I/O and "
            "CPU activity. Good for spotting whether a slow system is CPU-, "
            "memory- or disk-bound before digging further."
        ),
        flags=(
            Flag(
                ("1", "5"),
                "1 5  sample every second, 5 times",
                "Prints a fresh line of statistics once a second, five times "
                "in a row, so you can see whether load is steady or spiking.",
            ),
        ),
    ),
    Command(
        name="lsblk",
        description=(
            "Lists block devices (disks and partitions) as a tree, along with "
            "their size, filesystem type and mount point. Useful for making "
            "sense of storage layout before diagnosing a disk or mount issue."
        ),
    ),
]

NETWORK_COMMANDS: list[Command] = [
    Command(
        name="ss",
        description=(
            "Shows active sockets and their state — the modern replacement for "
            "netstat. Used to check which ports are listening, which remote "
            "connections are open, and which process owns a given socket."
        ),
        flags=(
            Flag(
                ("-t",),
                "-t  TCP sockets",
                "Restricts the listing to TCP sockets, hiding UDP and Unix "
                "domain sockets.",
            ),
            Flag(
                ("-u",),
                "-u  UDP sockets",
                "Restricts the listing to UDP sockets.",
            ),
            Flag(
                ("-l",),
                "-l  listening only",
                "Shows only sockets that are listening for incoming "
                "connections, i.e. services waiting for traffic.",
            ),
            Flag(
                ("-p",),
                "-p  show process",
                "Shows which process (PID and name) owns each socket. "
                "Usually needs root to see processes owned by other users.",
            ),
            Flag(
                ("-n",),
                "-n  numeric",
                "Shows numeric IP addresses and port numbers instead of "
                "resolving them to hostnames and service names, which is "
                "both faster and less ambiguous.",
            ),
        ),
    ),
    Command(
        name="ip",
        description=(
            "The modern tool for inspecting and configuring network "
            "interfaces, addresses and routing on Linux, replacing the older "
            "`ifconfig`/`route`. Used here read-only, to inspect the current "
            "network configuration."
        ),
        flags=(
            Flag(
                ("addr",),
                "addr  show interfaces",
                "Lists every network interface with its IP addresses, MAC "
                "address and current state (up/down) — the first thing to "
                "check when a machine seems to have no network.",
            ),
            Flag(
                ("route",),
                "route  show routing table",
                "Shows the kernel's routing table: which gateway traffic to "
                "each destination goes through, including the default route.",
            ),
            Flag(
                ("-s", "link"),
                "-s link  interface statistics",
                "Shows packet, byte and error counters per interface — "
                "useful for spotting dropped packets or a saturated link.",
            ),
        ),
    ),
    Command(
        name="ping",
        description=(
            "Sends ICMP echo requests to a host and reports round-trip time "
            "and packet loss. The most basic reachability test: if a host "
            "doesn't reply to ping, there's little point debugging anything "
            "higher up the stack until that's understood."
        ),
        flags=(
            Flag(
                ("-c", "4", "1.1.1.1"),
                "-c 4 1.1.1.1  ping Cloudflare DNS",
                "Sends 4 pings to Cloudflare's public DNS resolver (1.1.1.1), "
                "a good way to check general internet reachability without "
                "depending on DNS working.",
            ),
            Flag(
                ("-c", "4", "8.8.8.8"),
                "-c 4 8.8.8.8  ping Google DNS",
                "Sends 4 pings to Google's public DNS resolver (8.8.8.8), an "
                "alternative reachability check independent of DNS.",
            ),
        ),
    ),
    Command(
        name="tcpdump",
        description=(
            "Captures and prints network packets as they pass through an "
            "interface. The deepest level of network debugging available "
            "here: useful when `ss`/`ip` show a connection *should* work but "
            "something is still silently dropping or mangling traffic. "
            "Reading raw traffic requires root."
        ),
        requires_sudo=True,
        flags=(
            Flag(
                ("-i", "any"),
                "-i any  every interface",
                "Captures on every network interface at once, instead of "
                "just the default one, so you don't have to guess which "
                "interface the traffic is on.",
            ),
            Flag(
                ("-n",),
                "-n  no name resolution",
                "Prints raw IP addresses and port numbers instead of "
                "resolving them to hostnames, which is both faster and "
                "avoids extra DNS traffic while you're debugging the network.",
            ),
            Flag(
                ("-c", "50"),
                "-c 50  stop after 50 packets",
                "Captures exactly 50 packets and then exits automatically, "
                "so the capture doesn't run forever and flood the log pane.",
            ),
        ),
    ),
    Command(
        name="nmcli",
        description=(
            "Command-line interface to NetworkManager, the connection "
            "manager used by most desktop distros. Used here read-only, to "
            "inspect device and connection state without changing anything."
        ),
        flags=(
            Flag(
                ("device", "status"),
                "device status  device state",
                "Lists every network device NetworkManager knows about and "
                "its current state (connected, disconnected, unavailable...).",
            ),
            Flag(
                ("connection", "show"),
                "connection show  saved connections",
                "Lists every configured connection profile (Wi-Fi, Ethernet, "
                "VPN...) and which ones are currently active.",
            ),
        ),
    ),
    Command(
        name="journalctl",
        description=(
            "The systemd journal, scoped to just the NetworkManager service. "
            "The fastest way to see what NetworkManager itself logged around "
            "a connection failure, DHCP issue or Wi-Fi drop, without wading "
            "through the entire system journal."
        ),
        base_args=("-u", "NetworkManager"),
        requires_sudo=True,
        flags=(
            Flag(
                ("-f",),
                "-f  follow",
                "Keep watching for new NetworkManager log entries as they "
                "happen, e.g. while reconnecting to a network to see exactly "
                "what NetworkManager does and when it fails.",
            ),
            Flag(
                ("-b",),
                "-b  current boot",
                "Shows only NetworkManager logs from the current boot, "
                "skipping older history.",
            ),
        ),
    ),
]


PANELS: list[CommandPanel] = [
    CommandPanel("Logs", LOG_COMMANDS),
    CommandPanel("Network", NETWORK_COMMANDS),
]
