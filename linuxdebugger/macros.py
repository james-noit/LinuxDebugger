"""GPU macros: fixed command combinations that answer one specific
debugging question in a single shot.

Unlike a `Command` (one argv, raw streaming output), a macro runs a small
decision tree of probes and reduces them to a fixed set of label/value
fields -- a template. That's deliberate: a future live-updating monitor
will re-run the same probes and re-render the same template with fresh
values, so the fields need to stay fixed and predictable from the start
rather than being an arbitrary blob of text.

The decision tree matters as much as the template: every external tool
(nvidia-smi, rocm-smi, glxinfo, vulkaninfo...) is optional and vendor-
specific, so nothing is invoked speculatively. The baseline identification
(vendor, model, kernel driver) comes entirely from the kernel's own sysfs,
which needs no package installed at all. From there, which vendor branch
runs (NVIDIA vs. AMD/ROCm vs. Intel) is decided by the kernel driver that's
actually bound to the device, and each optional tool inside that branch is
only invoked once its presence has been checked with `shutil.which` --
never assumed.
"""

import asyncio
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

UNKNOWN = "unknown"

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


@dataclass(frozen=True)
class MacroResult:
    title: str
    fields: list[tuple[str, str]]


@dataclass(frozen=True)
class MacroRun:
    result: MacroResult
    raw_log: str


@dataclass(frozen=True)
class Macro:
    name: str
    description: str
    # The commands a run of this macro can involve, for display in the
    # confirmation dialog before anything actually executes. Since this is
    # a decision tree, not every step necessarily runs on every machine --
    # each one is only used once the tree reaches it and (for external
    # tools) confirms it's actually installed.
    steps: tuple[tuple[str, ...], ...]
    run: Callable[[], Awaitable[MacroRun]]


def _which(binary: str) -> bool:
    return shutil.which(binary) is not None


async def _exec(argv: tuple[str, ...]) -> tuple[str | None, str]:
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
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return None, "(command not found)"
    stdout, _ = await process.communicate()
    text = stdout.decode(errors="replace").rstrip()
    if process.returncode != 0:
        return None, text or f"(exited with code {process.returncode})"
    return text, text


def _guess_vendor(text: str) -> str:
    lowered = text.lower()
    if "nvidia" in lowered:
        return "NVIDIA"
    if "advanced micro devices" in lowered or "amd" in lowered or "ati " in lowered:
        return "AMD"
    if "intel" in lowered:
        return "Intel"
    return UNKNOWN


def _scan_pci_display_devices() -> list[dict[str, str]]:
    """Pure sysfs scan for PCI display-class devices (class 03xx) --
    zero dependency on any external tool, not even lspci. This is the
    kernel-level baseline the rest of the decision tree builds on."""
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


def _read_amdgpu_vram_bytes() -> int | None:
    """Best-effort VRAM size on AMD: the amdgpu kernel driver exposes it
    directly as a sysfs file, no extra tool needed."""
    for path in sorted(Path("/sys/class/drm").glob("card*/device/mem_info_vram_total")):
        try:
            return int(path.read_text().strip())
        except (OSError, ValueError):
            continue
    return None


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
    raw_chunks: list[str] = []

    def log_step(header: str, body: str) -> None:
        raw_chunks.append(f"$ {header}\n{body}\n")

    async def probe(argv: tuple[str, ...]) -> str | None:
        output, display_text = await _exec(argv)
        log_step(" ".join(argv), display_text)
        return output

    vendor = model = kernel_driver = UNKNOWN
    driver_version = vram_total = UNKNOWN
    opengl_renderer = vulkan_device = UNKNOWN

    # Step 1: pure sysfs scan, zero external dependencies -- this alone is
    # enough to answer "what GPU is this and what driver is bound to it"
    # on virtually any Linux system, regardless of what's installed.
    devices = _scan_pci_display_devices()
    if devices:
        device = devices[0]
        kernel_driver = device["kernel_driver"]
        vendor = PCI_VENDOR_NAMES.get(device["vendor_id"], UNKNOWN)
        model = f"PCI {device['vendor_id']}:{device['device_id']}"
        log_step(
            "read /sys/bus/pci/devices/*/{vendor,device,driver}",
            "\n".join(
                f"{d['slot']}: vendor={d['vendor_id']} device={d['device_id']} "
                f"driver={d['kernel_driver']}"
                for d in devices
            ),
        )
    else:
        log_step(
            "read /sys/bus/pci/devices/*/{vendor,device,driver}",
            "(no display-class PCI device found)",
        )

    if vendor == UNKNOWN:
        vendor = DRIVER_VENDOR_HINTS.get(kernel_driver, UNKNOWN)

    # Step 2: refine the model name via lspci's ID database, but only if
    # lspci is actually installed -- the sysfs scan above already gives a
    # complete, correct (if less pretty) answer without it.
    if _which("lspci"):
        lspci_out = await probe(("lspci", "-d", "::03xx", "-mmnn"))
        if lspci_out:
            first_line = lspci_out.splitlines()[0] if lspci_out.splitlines() else ""
            # -mmnn quotes exactly: slot "class" "vendor" "device" -r.. -p..
            # "svendor" "sdevice" -- revision/prog-if are bare, unquoted
            # tokens, so they don't shift these positions.
            quoted = re.findall(r'"((?:[^"\\]|\\.)*)"', first_line)
            if len(quoted) >= 3:
                model = f"{quoted[1]} {quoted[2]}"
    else:
        log_step("lspci", "(not installed -- using the raw PCI IDs from sysfs above)")

    # Step 3: vendor-specific branch. Nothing here is invoked unless its
    # presence has actually been confirmed first.
    if vendor == "NVIDIA":
        proc_version = Path("/proc/driver/nvidia/version")
        try:
            text = proc_version.read_text()
        except OSError:
            log_step(
                "cat /proc/driver/nvidia/version",
                "(not present -- proprietary driver not loaded, likely using nouveau)",
            )
        else:
            log_step("cat /proc/driver/nvidia/version", text.strip())
            match = re.search(r"Kernel Module\s+([\d.]+)", text)
            if match:
                driver_version = match.group(1)

        if _which("nvidia-smi"):
            nvsmi_out = await probe(
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
            log_step("nvidia-smi", "(not installed)")

    elif vendor == "AMD":
        vram_bytes = _read_amdgpu_vram_bytes()
        if vram_bytes is not None:
            vram_total = f"{vram_bytes / (1024 ** 3):.1f} GiB"
            log_step(
                "cat /sys/class/drm/card*/device/mem_info_vram_total", str(vram_bytes)
            )
        else:
            log_step(
                "cat /sys/class/drm/card*/device/mem_info_vram_total",
                "(not exposed by this driver)",
            )

        # AMD's compute stack (ROCm) is the ecosystem the ROCm tools live
        # in; Vulkan (checked further down, vendor-agnostic) is the
        # graphics-API side -- the two aren't substitutes for each other,
        # so both get checked independently rather than picking just one.
        if _which("rocm-smi"):
            rocm_out = await probe(("rocm-smi", "--showdriverversion"))
            if rocm_out:
                match = re.search(r"[Dd]river [Vv]ersion:\s*(\S+)", rocm_out)
                if match:
                    driver_version = match.group(1)
        elif _which("rocminfo"):
            await probe(("rocminfo",))
        else:
            log_step("rocm-smi / rocminfo", "(ROCm not installed)")

    elif vendor == "Intel":
        log_step(
            f"kernel driver: {kernel_driver}",
            "Intel GPU identified from the kernel driver; no Intel-specific "
            "CLI tool is queried here (intel_gpu_top needs root and stays "
            "in the GPU panel's command list instead).",
        )

    # Step 4: universal graphics-API checks. Vendor-agnostic (Mesa can back
    # any of the three vendors), so these run regardless of which branch
    # was taken above, but each is still gated on its own availability.
    if _which("glxinfo"):
        glx_out = await probe(("glxinfo", "-B"))
        if glx_out:
            renderer_match = re.search(r"OpenGL renderer string:\s*(.+)", glx_out)
            if renderer_match:
                opengl_renderer = renderer_match.group(1).strip()
            if vendor == UNKNOWN:
                vendor_match = re.search(r"OpenGL vendor string:\s*(.+)", glx_out)
                if vendor_match:
                    vendor = _guess_vendor(vendor_match.group(1))
    else:
        log_step("glxinfo", "(not installed)")

    if _which("vulkaninfo"):
        vk_out = await probe(("vulkaninfo", "--summary"))
        if vk_out:
            device_match = re.search(r"deviceName\s*=\s*(.+)", vk_out)
            if device_match:
                vulkan_device = device_match.group(1).strip()
            if driver_version == UNKNOWN:
                driver_match = re.search(r"driverInfo\s*=\s*(.+)", vk_out)
                if driver_match:
                    driver_version = driver_match.group(1).strip()
    else:
        log_step("vulkaninfo", "(not installed)")

    fields = [
        ("Vendor", vendor),
        ("Model", model),
        ("Kernel driver", kernel_driver),
        ("Driver version", driver_version),
        ("VRAM total", vram_total),
        ("OpenGL renderer", opengl_renderer),
        ("Vulkan device", vulkan_device),
    ]
    result = MacroResult(title="GPU Information", fields=fields)
    return MacroRun(result=result, raw_log="\n".join(raw_chunks))


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
]
