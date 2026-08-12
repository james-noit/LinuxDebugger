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


COMMANDS: list[Command] = [
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
                ("-T",),
                "-T  human-readable time",
                "Converts the kernel's raw monotonic timestamps into normal "
                "wall-clock date/time strings, which is far easier to line up "
                "against other logs or against when you noticed the problem.",
            ),
            Flag(
                ("-w",),
                "-w  follow",
                "Waits for and prints new kernel messages as they arrive, the "
                "dmesg equivalent of `tail -f`. Useful while plugging in "
                "hardware or reproducing a driver crash live.",
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
]
