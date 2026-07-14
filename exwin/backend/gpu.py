"""GPU detection via /sys/class/drm/ + optional lspci."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

_VENDOR_MAP = {
    "0x1002": "amd",
    "0x10de": "nvidia",
    "0x8086": "intel",
}


@dataclass
class GPU:
    index: int  # DRI_PRIME index
    name: str  # e.g. "AMD Radeon RX 7700S"
    vendor: str  # "amd" | "nvidia" | "intel" | "unknown"


_VULKAN_ICD_DIRS = (
    Path("/usr/share/vulkan/icd.d"),
    Path("/usr/local/share/vulkan/icd.d"),
    Path("/etc/vulkan/icd.d"),
)


def vulkan_available() -> bool:
    """True if a Vulkan ICD (driver manifest) or the vulkaninfo tool is present."""
    for icd_dir in _VULKAN_ICD_DIRS:
        try:
            if any(icd_dir.glob("*.json")):
                return True
        except OSError:
            continue
    return shutil.which("vulkaninfo") is not None


def detect_gpus() -> list[GPU]:
    """Enumerate GPUs from /sys/class/drm/card* entries."""
    drm = Path("/sys/class/drm")
    if not drm.is_dir():
        return []

    # Only match cardN (not card0-HDMI-A-1 etc.)
    card_dirs = sorted(p for p in drm.glob("card[0-9]*") if re.fullmatch(r"card\d+", p.name))

    pci_names = _parse_lspci()
    gpus: list[GPU] = []
    index = 0

    for card in card_dirs:
        vendor_file = card / "device" / "vendor"
        if not vendor_file.exists():
            continue

        vendor_hex = vendor_file.read_text().strip().lower()
        vendor = _VENDOR_MAP.get(vendor_hex, "unknown")
        name = _get_gpu_name(card, pci_names, vendor, index)

        gpus.append(GPU(index=index, name=name, vendor=vendor))
        index += 1

    return gpus


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_gpu_name(card: Path, pci_names: dict[str, str], vendor: str, index: int) -> str:
    """Try to resolve a human-readable GPU name via lspci output."""
    uevent = card / "device" / "uevent"
    if uevent.exists():
        for line in uevent.read_text().splitlines():
            if line.startswith("PCI_SLOT_NAME="):
                slot = line.split("=", 1)[1].strip()
                if slot in pci_names:
                    return pci_names[slot]

    vendor_label = vendor.capitalize() if vendor != "unknown" else "Unknown"
    return f"{vendor_label} GPU {index}"


def _parse_lspci() -> dict[str, str]:
    """Run lspci -vmm and return {pci_slot: device_name} for GPU-class devices."""
    try:
        result = subprocess.run(
            ["lspci", "-vmm"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {}

    names: dict[str, str] = {}
    slot = ""
    cls = ""
    device = ""

    for line in result.stdout.splitlines():
        if not line.strip():
            # End of a stanza — record if it's a GPU class
            if slot and device and _is_gpu_class(cls):
                names[slot] = device
            slot = cls = device = ""
            continue

        key, _, value = line.partition(":\t")
        key = key.strip()
        value = value.strip()
        if key == "Slot":
            slot = value
        elif key == "Class":
            cls = value
        elif key == "Device":
            device = value

    # Handle last stanza (no trailing blank line)
    if slot and device and _is_gpu_class(cls):
        names[slot] = device

    return names


def _is_gpu_class(cls: str) -> bool:
    return any(kw in cls for kw in ("VGA", "3D", "Display"))
