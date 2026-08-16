from dataclasses import dataclass, field


@dataclass(frozen=True)
class Flag:
    """An optional flag that can be toggled on for a command.

    A flag can also carry one customizable value token (e.g. the "today" in
    "--since today"). `value_index` points at which element of `tokens` that
    is; `proposed_values` seeds a picker with common choices, but the user
    can always type something else instead -- the list is just a starting
    point and can grow over time without any other code needing to change.
    """

    tokens: tuple[str, ...]
    label: str
    description: str
    value_index: int | None = None
    proposed_values: tuple[str, ...] = ()

    @property
    def customizable(self) -> bool:
        return self.value_index is not None

    def default_value(self) -> str | None:
        if self.value_index is None:
            return None
        return self.tokens[self.value_index]

    def resolved_tokens(self, value: str | None) -> tuple[str, ...]:
        if value is None or self.value_index is None:
            return self.tokens
        return (
            self.tokens[: self.value_index]
            + (value,)
            + self.tokens[self.value_index + 1 :]
        )

    def resolved_label(self, value: str | None) -> str:
        if value is None or self.value_index is None:
            return self.label
        # The label normally reads like "-p err  errors and worse" -- once
        # customized, show the actual value in place of the default instead
        # of the now-stale description suffix.
        return " ".join(self.resolved_tokens(value))


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
                "Filters the output down to the priority level you pick and "
                "everything more severe, hiding the rest so real failures "
                "stand out immediately.",
                value_index=1,
                proposed_values=(
                    "emerg",
                    "alert",
                    "crit",
                    "err",
                    "warning",
                    "notice",
                    "info",
                    "debug",
                ),
            ),
            Flag(
                ("--since", "today"),
                "--since today",
                "Shows only entries logged since the point in time you pick -- "
                "accepts journalctl's own time syntax (a keyword like 'today' "
                "or 'boot', a relative offset like '-1 hour', or an absolute "
                "'YYYY-MM-DD HH:MM:SS').",
                value_index=1,
                proposed_values=(
                    "today",
                    "yesterday",
                    "-15 min",
                    "-1 hour",
                    "-1 day",
                    "boot",
                ),
            ),
            Flag(
                ("-u", "sshd"),
                "-u sshd  scope to a unit",
                "Restricts the journal to just the service you pick -- the "
                "single most common way to use journalctl when you already "
                "know which service is misbehaving instead of wading through "
                "the entire system log.",
                value_index=1,
                proposed_values=(
                    "sshd",
                    "cron",
                    "docker",
                    "NetworkManager",
                    "systemd-logind",
                    "networking",
                ),
            ),
            Flag(
                ("-n", "200"),
                "-n 200  last N lines",
                "Shows only the most recent N entries instead of the whole "
                "history (or waiting on -f), a quick snapshot of 'what "
                "happened recently' without scrolling through everything.",
                value_index=1,
                proposed_values=("50", "100", "200", "500"),
            ),
            Flag(
                ("-r",),
                "-r  reverse (newest first)",
                "Prints entries newest-first instead of oldest-first, so the "
                "most recent activity is right at the top instead of at the "
                "bottom of a long scroll.",
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
                "Filters kernel messages down to the priority level you pick "
                "and everything more severe, hiding routine informational "
                "boot chatter so hardware and driver failures stand out.",
                value_index=1,
                proposed_values=(
                    "emerg",
                    "alert,emerg",
                    "crit,alert,emerg",
                    "err,crit,alert,emerg",
                    "warn,err,crit,alert,emerg",
                ),
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
            Flag(
                ("-f", "/var/log/syslog"),
                "-f <path>  custom file",
                "Follows any other plain-text log file you type the path to "
                "-- not every distro's logs fit the four presets above (e.g. "
                "/var/log/kern.log, /var/log/dpkg.log, or an application's "
                "own log file under /var/log).",
                value_index=1,
                proposed_values=(
                    "/var/log/syslog",
                    "/var/log/messages",
                    "/var/log/kern.log",
                    "/var/log/dpkg.log",
                    "/var/log/mail.log",
                ),
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
            Flag(
                ("-F",),
                "-F  full timestamps",
                "Shows complete date and time (including the year) for every "
                "entry instead of the default abbreviated format, so there's "
                "no ambiguity about exactly when a login or reboot happened.",
            ),
            Flag(
                ("-n", "50"),
                "-n 50  limit entries",
                "Shows only the N most recent entries instead of the entire "
                "wtmp history, which on a long-lived machine can otherwise be "
                "thousands of lines.",
                value_index=1,
                proposed_values=("10", "25", "50", "100"),
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
            Flag(
                ("status", "sshd"),
                "status sshd  one unit's status",
                "Shows the detailed status of the service you pick: whether "
                "it's active, its main PID, and its most recent log lines — "
                "the natural next step once you know which unit to look at.",
                value_index=1,
                proposed_values=(
                    "sshd",
                    "cron",
                    "docker",
                    "NetworkManager",
                    "systemd-logind",
                    "networking",
                ),
            ),
            Flag(
                ("list-timers",),
                "list-timers  scheduled timers",
                "Lists every systemd timer (the modern cron replacement), "
                "when it last ran and when it's next due — useful for "
                "tracking down a scheduled job that silently stopped firing.",
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
            Flag(
                ("-t",),
                "-t  totals row",
                "Adds a Total row summing memory and swap together, handy for "
                "seeing overall pressure at a glance instead of adding the "
                "two rows up yourself.",
            ),
            Flag(
                ("-s", "2"),
                "-s 2  live update every 2s",
                "Reprints the memory snapshot repeatedly at the interval (in "
                "seconds) you pick, like `vmstat`'s repeat mode -- useful for "
                "watching memory pressure build in real time. Only stops "
                "when you press Ctrl+K.",
                value_index=1,
                proposed_values=("1", "2", "5", "10"),
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
            Flag(
                ("-i",),
                "-i  inode usage",
                "Shows inode usage instead of block/space usage. A "
                "filesystem can run out of inodes (often from huge numbers "
                "of tiny files) while `df -h` still shows plenty of free "
                "space, so this catches a failure mode the default view "
                "completely misses.",
            ),
            Flag(
                ("-T",),
                "-T  show filesystem type",
                "Adds a column showing each mount's filesystem type (ext4, "
                "xfs, tmpfs, overlay...), useful for spotting an unexpected "
                "filesystem or a pseudo-filesystem eating into the listing.",
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
            Flag(
                ("aux", "--sort=-%cpu"),
                "aux --sort=-%cpu  top CPU first",
                "Same as the full listing above, but sorted with the "
                "heaviest CPU consumers at the top -- the fastest way to spot "
                "a runaway process without scanning the whole list by eye.",
            ),
            Flag(
                ("aux", "--sort=-%mem"),
                "aux --sort=-%mem  top memory first",
                "Same as the full listing above, but sorted with the "
                "heaviest memory consumers at the top -- useful for tracking "
                "down what's eating RAM before a machine starts swapping.",
            ),
            Flag(
                ("-ef", "--forest"),
                "-ef --forest  process tree",
                "Shows every process with its parent/child relationships "
                "drawn as an ASCII tree, which makes it obvious what spawned "
                "what -- handy for tracking down orphaned or zombie children "
                "of a crashed parent.",
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
                "Prints a fresh line of statistics once a second, for however "
                "many times you pick, so you can see whether load is steady "
                "or spiking.",
                value_index=1,
                proposed_values=("5", "10", "20", "30"),
            ),
            Flag(
                ("-a",),
                "-a  active/inactive memory",
                "Breaks the memory columns down into active and inactive "
                "pages instead of just used/free/buff/cache, a finer-grained "
                "view of memory pressure when the basic columns aren't "
                "telling the full story.",
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
        flags=(
            Flag(
                ("-f",),
                "-f  filesystem info",
                "Adds each partition's filesystem type, label and UUID to "
                "the tree -- the plain listing shows the storage layout but "
                "not what's actually formatted on each partition, which this "
                "fills in.",
            ),
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
            Flag(
                ("-a",),
                "-a  all sockets",
                "Shows both listening and established sockets together -- "
                "without this, listening sockets are hidden unless -l is "
                "also on, so this is the 'show me everything' option.",
            ),
            Flag(
                ("-s",),
                "-s  summary statistics",
                "Prints an overall summary instead of a per-socket listing: "
                "total counts by protocol and TCP state, a quick way to spot "
                "e.g. an unusually large number of connections stuck in "
                "TIME-WAIT or CLOSE-WAIT.",
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
            Flag(
                ("neigh",),
                "neigh  ARP/neighbor table",
                "Lists the kernel's neighbor table -- which MAC address it "
                "currently has cached for each IP on the local network -- "
                "the basic layer-2 reachability check for 'can I even see "
                "this host on the LAN'.",
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
                "depending on DNS working. Customize the target to ping any "
                "host or IP instead.",
                value_index=2,
                proposed_values=(
                    "1.1.1.1",
                    "8.8.8.8",
                    "9.9.9.9",
                    "google.com",
                    "github.com",
                ),
            ),
            Flag(
                ("-c", "4", "8.8.8.8"),
                "-c 4 8.8.8.8  ping Google DNS",
                "Sends 4 pings to Google's public DNS resolver (8.8.8.8), an "
                "alternative reachability check independent of DNS. Customize "
                "the target to ping any host or IP instead.",
                value_index=2,
                proposed_values=(
                    "8.8.8.8",
                    "1.1.1.1",
                    "9.9.9.9",
                    "google.com",
                    "github.com",
                ),
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
            Flag(
                ("port 443",),
                "port 443  capture filter",
                "Restricts the capture to traffic matching a BPF filter "
                "expression you pick -- without this, every packet on the "
                "interface is captured, which is noisy on a busy machine. "
                "Accepts the same syntax as tcpdump's own filter argument "
                "(e.g. 'port 80', 'host 1.1.1.1', 'icmp').",
                value_index=0,
                proposed_values=(
                    "port 443",
                    "port 80",
                    "icmp",
                    "udp port 53",
                    "host 1.1.1.1",
                ),
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
            Flag(
                ("general", "status"),
                "general status  overall connectivity",
                "Shows NetworkManager's own summary state: overall "
                "connectivity (full/limited/none), whether networking and "
                "Wi-Fi are enabled, and the current connection type -- a "
                "one-line sanity check before digging into individual "
                "devices or connections.",
            ),
            Flag(
                ("device", "wifi", "list"),
                "device wifi list  visible networks",
                "Lists every Wi-Fi network currently visible to this "
                "machine, with signal strength and security type -- useful "
                "for confirming the expected network is even in range before "
                "chasing a connection failure.",
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
            Flag(
                ("-n", "200"),
                "-n 200  last N lines",
                "Shows only the most recent N entries instead of the whole "
                "history, a quick snapshot without scrolling through "
                "everything NetworkManager has ever logged.",
                value_index=1,
                proposed_values=("50", "100", "200", "500"),
            ),
            Flag(
                ("-p", "err"),
                "-p err  errors and worse",
                "Filters NetworkManager's log down to the priority level you "
                "pick and everything more severe, hiding routine connection "
                "chatter so real failures stand out.",
                value_index=1,
                proposed_values=(
                    "emerg",
                    "alert",
                    "crit",
                    "err",
                    "warning",
                    "notice",
                    "info",
                    "debug",
                ),
            ),
        ),
    ),
]

GPU_COMMANDS: list[Command] = [
    Command(
        name="nvidia-smi",
        description=(
            "NVIDIA's own GPU management tool: a single-shot table of every "
            "NVIDIA GPU in the machine, its driver/CUDA version, temperature, "
            "power draw, memory usage and any processes currently using it. "
            "Only works if an NVIDIA GPU and its proprietary driver are "
            "installed — reports 'command not found' otherwise, which is "
            "itself a useful signal on an unfamiliar machine."
        ),
        flags=(
            Flag(
                ("-l", "1"),
                "-l 1  live refresh every 1s",
                "Reprints the full status table repeatedly at the interval "
                "(in seconds) you pick instead of a single snapshot, so you "
                "can watch utilization, memory and temperature change in "
                "real time while reproducing a workload. Only stops when you "
                "press Ctrl+K.",
                value_index=1,
                proposed_values=("1", "2", "5", "10"),
            ),
            Flag(
                ("pmon",),
                "pmon  per-process monitor",
                "Streams per-process GPU utilization and memory usage, one "
                "line per process per second — the fastest way to see "
                "exactly which process is actually using the GPU, rather "
                "than just the aggregate total.",
            ),
            Flag(
                (
                    "--query-gpu=utilization.gpu,utilization.memory,"
                    "memory.used,memory.total,temperature.gpu",
                    "--format=csv,noheader",
                ),
                "--query-gpu=...  compact utilization line",
                "Prints just the numbers that usually matter — GPU%, memory "
                "%, memory used/total and temperature — as one compact CSV "
                "line instead of the full table, handy for a quick glance "
                "or for pasting into a bug report.",
            ),
        ),
    ),
    Command(
        name="rocm-smi",
        description=(
            "AMD's ROCm System Management Interface — the amdgpu/ROCm "
            "equivalent of nvidia-smi. A single-shot table of every ROCm-"
            "visible AMD GPU: temperature, power draw, clocks, fan and "
            "utilization. Only works if the ROCm stack is installed and the "
            "GPU is supported — reports 'command not found' or an empty "
            "device list otherwise, which is itself a useful signal."
        ),
        flags=(
            Flag(
                ("--showallinfo",),
                "--showallinfo  everything",
                "Dumps every metric rocm-smi knows about a single device: "
                "clocks, voltage, power, temperature, memory, PCIe link "
                "state and more, instead of just the default summary table.",
            ),
            Flag(
                ("--showuse",),
                "--showuse  GPU/memory usage %",
                "Shows just the GPU and memory-controller busy percentages "
                "— the ROCm equivalent of the 'utilization.gpu' column in "
                "nvidia-smi, useful for a quick 'is it actually working "
                "hard' check.",
            ),
            Flag(
                ("--showmeminfo", "vram"),
                "--showmeminfo vram  memory detail",
                "Shows used/total memory for the pool you pick -- VRAM "
                "(dedicated GPU memory), visible VRAM (the CPU-accessible "
                "slice of it), GTT (system memory usable by the GPU), or "
                "all three -- useful when a compute job is running out of "
                "GPU memory.",
                value_index=1,
                proposed_values=("vram", "vis_vram", "gtt", "all"),
            ),
            Flag(
                ("--showtemp",),
                "--showtemp  temperature",
                "Shows temperature sensors across the GPU die, junction and "
                "memory, without the rest of the summary table getting in "
                "the way.",
            ),
            Flag(
                ("--showpids",),
                "--showpids  processes using the GPU",
                "Lists which processes currently have the GPU open — the "
                "ROCm equivalent of nvidia-smi's process list, useful for "
                "finding what's actually holding VRAM or compute resources.",
            ),
        ),
    ),
    Command(
        name="rocminfo",
        description=(
            "Queries the ROCm/HSA runtime for every compute agent it can "
            "see — CPUs and GPUs alike — with their name, compute "
            "capability (gfx target) and memory pools. The first thing to "
            "check when a ROCm application can't find the GPU at all: if "
            "the GPU isn't listed here, nothing built on top of ROCm "
            "(PyTorch, TensorFlow-ROCm, HIP...) will see it either."
        ),
    ),
    Command(
        name="glxinfo",
        description=(
            "Queries the OpenGL/GLX implementation actually in use: renderer "
            "name, OpenGL version, and — most importantly — whether direct "
            "(hardware-accelerated) rendering is enabled. If a desktop app "
            "or game is unexpectedly slow, 'direct rendering: No' here is "
            "usually the reason. Works with any GPU vendor via Mesa; part of "
            "the 'mesa-utils' package on most distros."
        ),
        base_args=("-B",),
    ),
    Command(
        name="vulkaninfo",
        description=(
            "Queries the Vulkan API implementation and every Vulkan-capable "
            "device the system can see (GPU or, on some setups, an LLVM "
            "software fallback) — useful for confirming Vulkan is actually "
            "wired up to real hardware before blaming an application for a "
            "rendering problem. Runs full (unsummarized) by default since "
            "the log pane's own search bar makes digging through the long "
            "output easy; part of the 'vulkan-tools' package on most "
            "distros."
        ),
        flags=(
            Flag(
                ("--summary",),
                "--summary  brief overview",
                "Collapses the normally huge device/extension/format dump "
                "down to just the essentials -- driver version, device "
                "name and API version per GPU -- for a quick glance instead "
                "of a wall of text.",
            ),
            Flag(
                ("--show-formats",),
                "--show-formats  full format support table",
                "Includes the complete per-format image property table in "
                "the output, which the default view otherwise abbreviates "
                "-- needed when checking whether a specific pixel format is "
                "actually supported.",
            ),
            Flag(
                ("-j",),
                "-j  JSON output",
                "Prints device capabilities as machine-readable JSON instead "
                "of formatted text, for feeding into another tool or "
                "diffing between two machines.",
            ),
        ),
    ),
    Command(
        name="clinfo",
        description=(
            "Queries every OpenCL platform and device the system can see "
            "(AMD via ROCm/Mesa, Intel, NVIDIA, or a CPU runtime) — the "
            "OpenCL counterpart to glxinfo/vulkaninfo. Useful for confirming "
            "a GPU is actually exposed to OpenCL before blaming a compute "
            "application for not finding it."
        ),
        flags=(
            Flag(
                ("-l",),
                "-l  short listing",
                "Lists just platform and device names instead of the full "
                "capability dump for each one, a quick glance at what's "
                "available before pulling the full detail on a specific "
                "device.",
            ),
        ),
    ),
    Command(
        name="lspci",
        description=(
            "Lists PCI devices, scoped here to display controllers (VGA, 3D "
            "and other GPU-class devices) with numeric vendor/device IDs and "
            "the kernel driver currently bound to each one (-k). That last "
            "part answers the single most common GPU question: is the "
            "machine actually using the driver you think it is (nvidia vs. "
            "nouveau, amdgpu vs. radeon, i915...)."
        ),
        base_args=("-nnk", "-d", "::03"),
        flags=(
            Flag(
                ("-v",),
                "-v  verbose",
                "Adds extra detail per device: memory/IO address ranges, "
                "IRQ line, and device capabilities — useful when the basic "
                "listing isn't enough to tell two similar devices apart.",
            ),
        ),
    ),
    Command(
        name="journalctl",
        description=(
            "The systemd journal, restricted to kernel messages (-k) whose "
            "text matches common GPU driver names (nvidia, nouveau, amdgpu, "
            "radeon, i915, or the generic drm subsystem). The fastest way to "
            "see what the GPU driver itself logged around a crash, mode-set "
            "failure or hang, without wading through the entire kernel log."
        ),
        base_args=("-k", "-g", "nvidia|nouveau|amdgpu|radeon|i915|drm"),
        requires_sudo=True,
        flags=(
            Flag(
                ("-f",),
                "-f  follow",
                "Keep watching for new matching kernel messages as they "
                "happen, e.g. while reproducing a GPU hang or display glitch "
                "live.",
            ),
            Flag(
                ("-b",),
                "-b  current boot",
                "Shows only matching messages from the current boot, "
                "skipping older history.",
            ),
            Flag(
                ("-n", "200"),
                "-n 200  last N lines",
                "Shows only the most recent N matching entries instead of "
                "the whole history, a quick snapshot without scrolling "
                "through everything.",
                value_index=1,
                proposed_values=("50", "100", "200", "500"),
            ),
            Flag(
                ("-p", "err"),
                "-p err  errors and worse",
                "Filters the matching messages down to the priority level "
                "you pick and everything more severe, hiding routine driver "
                "chatter so real failures stand out.",
                value_index=1,
                proposed_values=(
                    "emerg",
                    "alert",
                    "crit",
                    "err",
                    "warning",
                    "notice",
                    "info",
                    "debug",
                ),
            ),
        ),
    ),
    Command(
        name="radeontop",
        description=(
            "Live utilization monitor for AMD GPUs (via the amdgpu/radeon "
            "kernel driver's performance counters): GPU, memory controller "
            "and video engine load, refreshed continuously. Run here in "
            "dump mode (-d -) so it streams plain text instead of grabbing "
            "the terminal like its default full-screen UI does."
        ),
        base_args=("-d", "-"),
        flags=(
            Flag(
                ("-l", "10"),
                "-l 10  stop after N samples",
                "Prints exactly N samples and then exits automatically, "
                "instead of streaming forever — useful for capturing a "
                "short window without needing to press Ctrl+K.",
                value_index=1,
                proposed_values=("5", "10", "20", "50"),
            ),
        ),
    ),
    Command(
        name="intel_gpu_top",
        description=(
            "Live utilization monitor for Intel integrated/discrete GPUs: "
            "render/video/blitter engine busy percentages and power usage, "
            "refreshed continuously. Run here in stdout mode (-o -) so it "
            "streams plain text instead of grabbing the terminal like its "
            "default full-screen UI does. Needs root on most systems because "
            "it reads GPU performance counters through perf."
        ),
        base_args=("-o", "-"),
        requires_sudo=True,
        flags=(
            Flag(
                ("-s", "1000"),
                "-s 1000  sample interval (ms)",
                "Sets how often (in milliseconds) a new sample is printed — "
                "lower values give a smoother live view at the cost of more "
                "output; higher values are easier to read line by line.",
                value_index=1,
                proposed_values=("100", "500", "1000", "2000"),
            ),
        ),
    ),
]


PANELS: list[CommandPanel] = [
    CommandPanel("Logs", LOG_COMMANDS),
    CommandPanel("Network", NETWORK_COMMANDS),
    CommandPanel("GPU", GPU_COMMANDS),
]
