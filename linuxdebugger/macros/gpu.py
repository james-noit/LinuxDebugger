"""GPU-panel macros.

Baseline vendor/model/kernel-driver identification comes entirely from the
kernel's own sysfs (`_scan_pci_display_devices` below) -- no package needed
at all. Every macro in this module reuses that same scan and branches on
the *kernel driver actually bound to the device* to decide which vendor-
specific tool (if any, and only if installed) can add more detail.
"""

import os
import re
from pathlib import Path

from .common import Macro, MacroResult, MacroRun, RawLog, StatusItem, UNKNOWN, which

PCI_VENDOR_NAMES = {
    "0x10de": "NVIDIA",
    "0x1002": "AMD",
    "0x8086": "Intel",
}

DRIVER_VENDOR_HINTS = {
    "nvidia": "NVIDIA",
    "nouveau": "NVIDIA",
    "amdgpu": "AMD",
    "radeon": "AMD",
    "i915": "Intel",
    "xe": "Intel",
}


def _guess_vendor(text: str) -> str:
    lowered = text.lower()
    if "nvidia" in lowered:
        return "NVIDIA"
    if "advanced micro devices" in lowered or "amd" in lowered or "ati " in lowered:
        return "AMD"
    if "intel" in lowered:
        return "Intel"
    return UNKNOWN


def scan_pci_display_devices() -> list[dict[str, str]]:
    """Pure sysfs scan for PCI display-class devices (class 03xx) -- zero
    dependency on any external tool, not even lspci."""
    base = Path("/sys/bus/pci/devices")
    devices: list[dict[str, str]] = []
    if not base.is_dir():
        return devices

    for dev_dir in sorted(base.iterdir()):
        try:
            class_hex = (dev_dir / "class").read_text().strip()
        except OSError:
            continue
        if not class_hex.startswith("0x03"):
            continue

        def _read(name: str) -> str:
            try:
                return (dev_dir / name).read_text().strip()
            except OSError:
                return UNKNOWN

        driver_link = dev_dir / "driver"
        kernel_driver = driver_link.resolve().name if driver_link.is_symlink() else UNKNOWN

        devices.append(
            {
                "slot": dev_dir.name,
                "vendor_id": _read("vendor"),
                "device_id": _read("device"),
                "kernel_driver": kernel_driver,
            }
        )
    return devices


def primary_gpu() -> tuple[str, str] | None:
    """Returns (vendor, kernel_driver) for the first display device found,
    or None if there isn't one."""
    devices = scan_pci_display_devices()
    if not devices:
        return None
    device = devices[0]
    vendor = PCI_VENDOR_NAMES.get(device["vendor_id"], UNKNOWN)
    if vendor == UNKNOWN:
        vendor = DRIVER_VENDOR_HINTS.get(device["kernel_driver"], UNKNOWN)
    return vendor, device["kernel_driver"]


def read_amdgpu_vram_bytes(which_file: str = "mem_info_vram_total") -> int | None:
    """Best-effort VRAM size/usage on AMD: the amdgpu kernel driver exposes
    it directly as a sysfs file, no extra tool needed."""
    for path in sorted(Path("/sys/class/drm").glob(f"card*/device/{which_file}")):
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):
            continue
    return None


# -- Identify GPU information ------------------------------------------

IDENTIFY_GPU_STEPS: tuple[tuple[str, ...], ...] = (
    ("read", "/sys/bus/pci/devices/*/{vendor,device,driver}"),
    ("lspci", "-d", "::03xx", "-mmnn"),
    ("cat", "/proc/driver/nvidia/version"),
    ("nvidia-smi", "--query-gpu=driver_version,memory.total", "--format=csv,noheader,nounits"),
    ("cat", "/sys/class/drm/card*/device/mem_info_vram_total"),
    ("rocm-smi", "--showdriverversion"),
    ("rocminfo",),
    ("glxinfo", "-B"),
    ("vulkaninfo", "--summary"),
)


async def identify_gpu() -> MacroRun:
    log = RawLog()

    vendor = model = kernel_driver = UNKNOWN
    driver_version = vram_total = UNKNOWN
    opengl_renderer = vulkan_device = UNKNOWN

    devices = scan_pci_display_devices()
    if devices:
        device = devices[0]
        kernel_driver = device["kernel_driver"]
        vendor = PCI_VENDOR_NAMES.get(device["vendor_id"], UNKNOWN)
        model = f"PCI {device['vendor_id']}:{device['device_id']}"
        log.note(
            "read /sys/bus/pci/devices/*/{vendor,device,driver}",
            "\n".join(
                f"{d['slot']}: vendor={d['vendor_id']} device={d['device_id']} "
                f"driver={d['kernel_driver']}"
                for d in devices
            ),
        )
    else:
        log.note(
            "read /sys/bus/pci/devices/*/{vendor,device,driver}",
            "(no display-class PCI device found)",
        )

    if vendor == UNKNOWN:
        vendor = DRIVER_VENDOR_HINTS.get(kernel_driver, UNKNOWN)

    if which("lspci"):
        lspci_out = await log.probe(("lspci", "-d", "::03xx", "-mmnn"))
        if lspci_out:
            first_line = lspci_out.splitlines()[0] if lspci_out.splitlines() else ""
            quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', first_line)
            if len(quoted) >= 3:
                model = f"{quoted[1]} {quoted[2]}"
    else:
        log.note("lspci", "(not installed -- using the raw PCI IDs from sysfs above)")

    if vendor == "NVIDIA":
        proc_version = Path("/proc/driver/nvidia/version")
        try:
            text = proc_version.read_text()
        except OSError:
            log.note(
                "cat /proc/driver/nvidia/version",
                "(not present -- proprietary driver not loaded, likely using nouveau)",
            )
        else:
            log.note("cat /proc/driver/nvidia/version", text.strip())
            match = re.search(r"Kernel Module\s+([\d.]+)", text)
            if match:
                driver_version = match.group(1)

        if which("nvidia-smi"):
            nvsmi_out = await log.probe(
                (
                    "nvidia-smi",
                    "--query-gpu=driver_version,memory.total",
                    "--format=csv,noheader,nounits",
                )
            )
            if nvsmi_out and nvsmi_out.strip():
                parts = [p.strip() for p in nvsmi_out.strip().splitlines()[0].split(",")]
                if len(parts) == 2:
                    if driver_version == UNKNOWN:
                        driver_version = parts[0]
                    vram_total = f"{parts[1]} MiB"
        else:
            log.note("nvidia-smi", "(not installed)")

    elif vendor == "AMD":
        vram_bytes = read_amdgpu_vram_bytes()
        if vram_bytes is not None:
            vram_total = f"{vram_bytes / (1024 ** 3):.1f} GiB"
            log.note("cat /sys/class/drm/card*/device/mem_info_vram_total", str(vram_bytes))
        else:
            log.note(
                "cat /sys/class/drm/card*/device/mem_info_vram_total",
                "(not exposed by this driver)",
            )

        if which("rocm-smi"):
            rocm_out = await log.probe(("rocm-smi", "--showdriverversion"))
            if rocm_out:
                match = re.search(r"[Dd]river [Vv]ersion:\s*(\S+)", rocm_out)
                if match:
                    driver_version = match.group(1)
        elif which("rocminfo"):
            await log.probe(("rocminfo",))
        else:
            log.note("rocm-smi / rocminfo", "(ROCm not installed)")

    elif vendor == "Intel":
        log.note(
            f"kernel driver: {kernel_driver}",
            "Intel GPU identified from the kernel driver; no Intel-specific "
            "CLI tool is queried here (intel_gpu_top needs root and stays "
            "in the GPU panel's command list instead).",
        )

    if which("glxinfo"):
        glx_out = await log.probe(("glxinfo", "-B"))
        if glx_out:
            renderer_match = re.search(r"OpenGL renderer string:\s*(.+)", glx_out)
            if renderer_match:
                opengl_renderer = renderer_match.group(1).strip()
            if vendor == UNKNOWN:
                vendor_match = re.search(r"OpenGL vendor string:\s*(.+)", glx_out)
                if vendor_match:
                    vendor = _guess_vendor(vendor_match.group(1))
    else:
        log.note("glxinfo", "(not installed)")

    if which("vulkaninfo"):
        vk_out = await log.probe(("vulkaninfo", "--summary"))
        if vk_out:
            device_match = re.search(r"deviceName\s*=\s*(.+)", vk_out)
            if device_match:
                vulkan_device = device_match.group(1).strip()
            if driver_version == UNKNOWN:
                driver_match = re.search(r"driverInfo\s*=\s*(.+)", vk_out)
                if driver_match:
                    driver_version = driver_match.group(1).strip()
    else:
        log.note("vulkaninfo", "(not installed)")

    items = [
        StatusItem("Vendor", vendor),
        StatusItem("Model", model),
        StatusItem("Kernel driver", kernel_driver),
        StatusItem("Driver version", driver_version),
        StatusItem("VRAM total", vram_total),
        StatusItem("OpenGL renderer", opengl_renderer),
        StatusItem("Vulkan device", vulkan_device),
    ]
    result = MacroResult(title="GPU Information", items=items, kind="fields")
    return MacroRun(result=result, raw_log=log.text())


# -- GPU errors / resets check -------------------------------------------

_CRASH_PATTERNS: dict[str, tuple[str, str]] = {
    # vendor: (grep-style regex for journalctl -g, plain re for our own search)
    "NVIDIA": (r"NVRM: Xid", r"NVRM:\s*Xid"),
    "AMD": (
        r"amdgpu.*(reset|timeout|GPU reset)",
        r"amdgpu.*(reset|timeout|GPU reset)",
    ),
    "Intel": (r"i915.*(GPU HANG|hangcheck)", r"i915.*(GPU HANG|hangcheck)"),
}

GPU_ERRORS_STEPS: tuple[tuple[str, ...], ...] = (
    ("read", "/sys/bus/pci/devices/*/driver"),
    ("journalctl", "-k", "-b", "-g", "<vendor crash pattern>"),
    ("dmesg", "-T"),
)


async def gpu_errors_check() -> MacroRun:
    log = RawLog()

    info = primary_gpu()
    if info is None:
        log.note(
            "read /sys/bus/pci/devices/*/driver", "(no display-class PCI device found)"
        )
        items = [StatusItem("GPU detected", "none found", level="unknown")]
        return MacroRun(
            result=MacroResult(title="GPU Errors & Resets", items=items, kind="semaphore"),
            raw_log=log.text(),
        )

    vendor, kernel_driver = info
    log.note("read /sys/bus/pci/devices/*/driver", f"vendor={vendor} driver={kernel_driver}")

    patterns = _CRASH_PATTERNS.get(vendor)
    items = [StatusItem("Kernel driver", f"{kernel_driver} ({vendor})", level="neutral")]

    if patterns is None:
        items.append(
            StatusItem(
                "Crash signature check",
                f"no known signature for {vendor}",
                level="unknown",
            )
        )
        return MacroRun(
            result=MacroResult(title="GPU Errors & Resets", items=items, kind="semaphore"),
            raw_log=log.text(),
        )

    grep_pattern, py_pattern = patterns
    output: str | None = None
    source = None
    if which("journalctl"):
        output = await log.probe(
            ("journalctl", "-k", "-b", "-g", grep_pattern, "-q", "-o", "cat"), grep=True
        )
        source = "journalctl"
    if output is None and which("dmesg"):
        output = await log.probe(("dmesg", "-T"))
        source = "dmesg"

    if output is None:
        items.append(
            StatusItem(
                "Crash signature check",
                "journalctl/dmesg unavailable or permission denied",
                level="unknown",
            )
        )
        return MacroRun(
            result=MacroResult(title="GPU Errors & Resets", items=items, kind="semaphore"),
            raw_log=log.text(),
        )

    matches = re.findall(py_pattern, output, re.IGNORECASE)
    count = len(matches)
    items.append(
        StatusItem(
            "Crash/reset signatures",
            f"{count} found via {source} (pattern: {vendor} known signature)",
            level="crit" if count else "ok",
        )
    )

    if count:
        lines = [line for line in output.splitlines() if re.search(py_pattern, line, re.IGNORECASE)]
        most_recent = lines[-1].strip() if lines else UNKNOWN
        items.append(StatusItem("Most recent occurrence", most_recent[:120], level="crit"))
    else:
        items.append(StatusItem("Most recent occurrence", "none in current boot", level="ok"))

    result = MacroResult(title="GPU Errors & Resets", items=items, kind="semaphore")
    return MacroRun(result=result, raw_log=log.text())


# -- GPU utilization snapshot ---------------------------------------------

UTILIZATION_STEPS: tuple[tuple[str, ...], ...] = (
    ("read", "/sys/bus/pci/devices/*/driver"),
    ("nvidia-smi", "--query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu", "--format=csv,noheader,nounits"),
    ("cat", "/sys/class/drm/card*/device/gpu_busy_percent"),
    ("cat", "/sys/class/drm/card*/device/mem_info_vram_used"),
)


def _level_for_percent(percent: float, warn_at: float = 70, crit_at: float = 90) -> str:
    if percent >= crit_at:
        return "crit"
    if percent >= warn_at:
        return "warn"
    return "ok"


async def gpu_utilization_snapshot() -> MacroRun:
    log = RawLog()

    info = primary_gpu()
    if info is None:
        log.note("read /sys/bus/pci/devices/*/driver", "(no display-class PCI device found)")
        items = [StatusItem("GPU detected", "none found", level="unknown")]
        return MacroRun(
            result=MacroResult(title="GPU Utilization", items=items, kind="gauge"),
            raw_log=log.text(),
        )

    vendor, kernel_driver = info
    log.note("read /sys/bus/pci/devices/*/driver", f"vendor={vendor} driver={kernel_driver}")
    items: list[StatusItem] = []

    if vendor == "NVIDIA" and which("nvidia-smi"):
        output = await log.probe(
            (
                "nvidia-smi",
                "--query-gpu=utilization.gpu,utilization.memory,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            )
        )
        if output and output.strip():
            parts = [p.strip() for p in output.strip().splitlines()[0].split(",")]
            if len(parts) == 5:
                gpu_pct, mem_pct, mem_used, mem_total, temp = (float(p) for p in parts)
                items.append(
                    StatusItem(
                        "GPU utilization",
                        f"{gpu_pct:.0f}%",
                        percent=gpu_pct,
                        level=_level_for_percent(gpu_pct, warn_at=101, crit_at=101),
                    )
                )
                vram_pct = (mem_used / mem_total * 100) if mem_total else 0.0
                items.append(
                    StatusItem(
                        "VRAM used",
                        f"{mem_used:.0f} / {mem_total:.0f} MiB",
                        percent=vram_pct,
                        level=_level_for_percent(vram_pct),
                    )
                )
                items.append(
                    StatusItem(
                        "Temperature",
                        f"{temp:.0f}°C",
                        percent=min(temp, 100.0),
                        level=_level_for_percent(temp, warn_at=75, crit_at=90),
                    )
                )
    elif vendor == "AMD":
        busy = read_amdgpu_vram_bytes("gpu_busy_percent")
        log.note(
            "cat /sys/class/drm/card*/device/gpu_busy_percent",
            str(busy) if busy is not None else "(not exposed by this driver)",
        )
        if busy is not None:
            items.append(
                StatusItem(
                    "GPU utilization",
                    f"{busy}%",
                    percent=float(busy),
                    level=_level_for_percent(float(busy), warn_at=101, crit_at=101),
                )
            )

        vram_total = read_amdgpu_vram_bytes("mem_info_vram_total")
        vram_used = read_amdgpu_vram_bytes("mem_info_vram_used")
        log.note(
            "cat /sys/class/drm/card*/device/mem_info_vram_used",
            str(vram_used) if vram_used is not None else "(not exposed by this driver)",
        )
        if vram_total and vram_used is not None:
            vram_pct = vram_used / vram_total * 100
            items.append(
                StatusItem(
                    "VRAM used",
                    f"{vram_used / (1024 ** 3):.1f} / {vram_total / (1024 ** 3):.1f} GiB",
                    percent=vram_pct,
                    level=_level_for_percent(vram_pct),
                )
            )
    else:
        log.note(
            f"kernel driver: {kernel_driver}",
            f"No zero-dependency utilization counter known for {vendor}; "
            "use intel_gpu_top from the GPU panel's command list instead.",
        )

    if not items:
        items.append(
            StatusItem(
                "GPU utilization",
                "unavailable (tool not installed or not exposed by driver)",
                level="unknown",
            )
        )

    result = MacroResult(title="GPU Utilization", items=items, kind="gauge")
    return MacroRun(result=result, raw_log=log.text())


# -- Display session check -------------------------------------------------

DISPLAY_SESSION_STEPS: tuple[tuple[str, ...], ...] = (
    ("read", "$XDG_SESSION_TYPE / $WAYLAND_DISPLAY / $DISPLAY"),
    ("xrandr", "--current"),
    ("wlr-randr",),
)


async def display_session_check() -> MacroRun:
    log = RawLog()

    session_type = os.environ.get("XDG_SESSION_TYPE", UNKNOWN)
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
    x_display = os.environ.get("DISPLAY", "")
    log.note(
        "read $XDG_SESSION_TYPE / $WAYLAND_DISPLAY / $DISPLAY",
        f"XDG_SESSION_TYPE={session_type or UNKNOWN} "
        f"WAYLAND_DISPLAY={wayland_display or '(unset)'} "
        f"DISPLAY={x_display or '(unset)'}",
    )

    server = "unknown"
    if wayland_display:
        server = f"Wayland ({wayland_display})"
    elif x_display:
        server = f"X11 ({x_display})"

    resolution = UNKNOWN
    if x_display and which("xrandr"):
        output = await log.probe(("xrandr", "--current"))
        if output:
            match = re.search(r"\s(\d{3,5}x\d{3,5})\+\d+\+\d+\s+\(", output)
            if not match:
                match = re.search(r"current\s+(\d+\s*x\s*\d+)", output)
            if match:
                resolution = match.group(1).replace(" ", "")
    elif wayland_display and which("wlr-randr"):
        output = await log.probe(("wlr-randr",))
        if output:
            match = re.search(r"(\d{3,5}x\d{3,5})\s+px", output)
            if match:
                resolution = match.group(1)
    else:
        log.note("xrandr / wlr-randr", "(not applicable or not installed)")

    items = [
        StatusItem("Session type", session_type or UNKNOWN),
        StatusItem("Display server", server),
        StatusItem("Resolution", resolution),
    ]
    result = MacroResult(title="Display Session", items=items, kind="fields")
    return MacroRun(result=result, raw_log=log.text())


GPU_MACROS: list[Macro] = [
    Macro(
        name="Identify GPU information",
        description=(
            "Runs a kernel-first decision tree: baseline vendor, model and "
            "kernel driver come straight from sysfs (no package needed at "
            "all), which vendor branch runs next (NVIDIA / proc+nvidia-smi, "
            "AMD / sysfs+ROCm, or Intel) is decided by the kernel driver "
            "actually bound to the device, and every external tool in that "
            "branch -- nvidia-smi, rocm-smi/rocminfo, glxinfo, vulkaninfo "
            "-- is only invoked after confirming it's installed. Fields "
            "that stay undeterminable show as 'unknown' rather than a "
            "wrong guess."
        ),
        steps=IDENTIFY_GPU_STEPS,
        run=identify_gpu,
    ),
    Macro(
        name="GPU errors & resets check",
        description=(
            "Detects the GPU vendor from the kernel driver, then searches "
            "the kernel log for that vendor's known crash/reset signature "
            "(NVRM Xid for NVIDIA, reset/timeout for amdgpu, GPU HANG for "
            "i915) via journalctl if available, falling back to dmesg. "
            "Shown as a semaphore: green if clean, red if a signature was "
            "found, with the most recent occurrence."
        ),
        steps=GPU_ERRORS_STEPS,
        run=gpu_errors_check,
    ),
    Macro(
        name="GPU utilization snapshot",
        description=(
            "A one-shot read of GPU/VRAM load -- the fixed-values stepping "
            "stone toward a future live monitor. NVIDIA via nvidia-smi's "
            "query interface if installed; AMD via the amdgpu sysfs busy-"
            "percent and VRAM-used counters (zero dependency); shown as "
            "gauges."
        ),
        steps=UTILIZATION_STEPS,
        run=gpu_utilization_snapshot,
    ),
    Macro(
        name="Display session check",
        description=(
            "Reports whether the current session is Wayland or X11 (from "
            "environment variables, zero dependency) and its resolution "
            "via xrandr or wlr-randr, whichever applies -- a quick sanity "
            "check before blaming the GPU driver for what's actually a "
            "compositor or display-manager issue."
        ),
        steps=DISPLAY_SESSION_STEPS,
        run=display_session_check,
    ),
]
