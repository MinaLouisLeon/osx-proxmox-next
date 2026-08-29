"""Enumerate the host devices that can be passed through to a VM.

PCI comes from ``pvesh get /nodes/<node>/hardware/pci``, which is what the
Proxmox PCI(e) passthrough wiki documents and which reports the IOMMU group --
the thing that actually decides whether a device can be handed to a guest.
There is no equally documented USB endpoint, so USB comes from ``lsusb``, which
is what the Proxmox USB wiki tells you to run. Both fall back to the plain
``lspci``/``lsusb`` output when the API call is unavailable, so a non-Proxmox
box (or a node whose name we guessed wrong) degrades to an empty list rather
than an error.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from ..infrastructure import ProxmoxAdapter
from .proxmox_service import get_proxmox_adapter

log = logging.getLogger(__name__)

__all__ = [
    "PciDevice",
    "UsbDevice",
    "AMD_VENDOR_ID",
    "detect_node_name",
    "detect_pci_devices",
    "detect_gpu_devices",
    "detect_usb_devices",
]

# PCI vendor 0x1002 is AMD/ATI. macOS ships drivers for AMD graphics only --
# NVIDIA has had no macOS driver since High Sierra -- so the GPU picker offers
# AMD cards and nothing else. The free-text field still accepts any address.
AMD_VENDOR_ID = "1002"

# PCI class 0x03xx is "Display controller".
_DISPLAY_CLASS_PREFIX = "0x03"


@dataclass(frozen=True)
class PciDevice:
    """A PCI device on the host, as offered for passthrough."""

    slot: str          # "0000:01:00.0" or "01:00.0"
    vendor_id: str     # "1002"
    device_id: str     # "73ff"
    description: str   # "Advanced Micro Devices [AMD/ATI] Navi 23"
    class_id: str = ""     # "0x030000"
    iommu_group: str = ""  # "" when the host reports none

    @property
    def function_group(self) -> str:
        """Return the address with the function dropped.

        ``qm set -hostpci0 01:00`` passes every function of the device, which
        is how a GPU and its HDMI audio function reach the guest together --
        macOS wants both. ``01:00.0`` would pass the video function alone.
        """
        return self.slot.rsplit(".", 1)[0] if "." in self.slot else self.slot

    @property
    def label(self) -> str:
        group = f"  [IOMMU {self.iommu_group}]" if self.iommu_group else ""
        return f"{self.function_group}  {self.description}{group}"


@dataclass(frozen=True)
class UsbDevice:
    """A USB device on the host, addressed the way ``qm set -usb0 host=`` wants."""

    device_id: str     # "058f:6387"
    description: str   # "Alcor Micro Corp. Flash Drive"

    @property
    def label(self) -> str:
        return f"{self.device_id}  {self.description}"


def detect_node_name(adapter: ProxmoxAdapter | None = None) -> str:
    """Return this Proxmox node's name, or "" when it cannot be determined.

    The hardware API is per-node, so the name has to be right. ``pvesh get
    /nodes`` is authoritative; ``hostname`` matches it on a normal install and
    covers the case where pvesh is not on PATH.
    """
    pve = adapter or get_proxmox_adapter()
    res = pve.pvesh("get", "/nodes", "--output-format", "json")
    if res.ok:
        try:
            nodes = json.loads(res.output)
        except (json.JSONDecodeError, ValueError):
            log.debug("pvesh /nodes returned non-JSON: %s", res.output)
        else:
            names = [n.get("node", "") for n in nodes if isinstance(n, dict)]
            names = [n for n in names if n]
            if names:
                # A single-node install is the common case; on a cluster prefer
                # the local hostname, since only local hardware is passable.
                local = pve.run(["hostname"])
                short = local.output.strip().split(".")[0] if local.ok else ""
                return short if short in names else names[0]
    res = pve.run(["hostname"])
    if res.ok and res.output.strip():
        return res.output.strip().split(".")[0]
    log.debug("Could not determine node name")
    return ""


def _pci_from_api(pve: ProxmoxAdapter, node: str) -> list[PciDevice] | None:
    """Return PCI devices via the Proxmox API, or None when unavailable."""
    res = pve.pvesh(
        "get", f"/nodes/{node}/hardware/pci",
        "--pci-class-blacklist", "",
        "--output-format", "json",
    )
    if not res.ok:
        log.debug("pvesh hardware/pci failed: %s", res.output)
        return None
    try:
        entries = json.loads(res.output)
    except (json.JSONDecodeError, ValueError):
        log.debug("pvesh hardware/pci returned non-JSON: %s", res.output)
        return None
    devices: list[PciDevice] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        slot = str(entry.get("id", "")).strip()
        if not slot:
            continue
        # The API reports ids as 0x1002; the config and lspci use bare hex.
        vendor = str(entry.get("vendor", "")).lower().removeprefix("0x")
        device = str(entry.get("device", "")).lower().removeprefix("0x")
        description = " ".join(
            part for part in (
                str(entry.get("vendor_name", "")).strip(),
                str(entry.get("device_name", "")).strip(),
            ) if part
        ) or slot
        iommu = entry.get("iommugroup", "")
        # -1 is the API's "no IOMMU group", which is not a usable group.
        iommu = "" if iommu in ("", None, -1, "-1") else str(iommu)
        devices.append(PciDevice(
            slot=slot,
            vendor_id=vendor,
            device_id=device,
            description=description,
            class_id=str(entry.get("class", "")),
            iommu_group=iommu,
        ))
    return devices


# "01:00.0 VGA compatible controller [0300]: Advanced Micro Devices ... [1002:73ff] (rev c7)"
_LSPCI_RE = re.compile(
    r"^(?P<slot>[0-9a-fA-F:.]+)\s+"
    r"(?P<desc>.*?)\s*\[(?P<cls>[0-9a-fA-F]{4})\]:\s*"
    r"(?P<name>.*?)\s*\[(?P<vendor>[0-9a-fA-F]{4}):(?P<device>[0-9a-fA-F]{4})\]"
)


def _pci_from_lspci(pve: ProxmoxAdapter) -> list[PciDevice]:
    """Return PCI devices parsed from ``lspci -nn``.

    Used when the API is not reachable. No IOMMU group is available here, so
    the picker simply does not show one.
    """
    res = pve.run(["lspci", "-Dnn"])
    if not res.ok:
        log.debug("lspci failed: %s", res.output)
        return []
    devices: list[PciDevice] = []
    for line in res.output.splitlines():
        match = _LSPCI_RE.match(line.strip())
        if not match:
            continue
        devices.append(PciDevice(
            slot=match.group("slot"),
            vendor_id=match.group("vendor").lower(),
            device_id=match.group("device").lower(),
            description=f"{match.group('desc')}: {match.group('name')}",
            class_id=f"0x{match.group('cls').lower()}",
        ))
    return devices


def detect_pci_devices(adapter: ProxmoxAdapter | None = None,
                       node: str | None = None) -> list[PciDevice]:
    """Return every PCI device on the host, or [] when none can be listed."""
    pve = adapter or get_proxmox_adapter()
    node_name = node if node is not None else detect_node_name(pve)
    devices = _pci_from_api(pve, node_name) if node_name else None
    if devices is None:
        devices = _pci_from_lspci(pve)
    return devices


def detect_gpu_devices(adapter: ProxmoxAdapter | None = None,
                       node: str | None = None) -> list[PciDevice]:
    """Return the AMD graphics cards on the host.

    Filtered to display-class AMD devices: those are the only ones macOS has a
    driver for, and offering an NVIDIA card in a macOS tool would be offering a
    black screen. Anything else can still be typed into the free-text field.

    Only the video function is listed, not the HDMI audio function that shares
    the slot -- attaching the video function's slot passes both (see
    ``PciDevice.function_group``), so listing the audio separately would just
    invite attaching it twice.
    """
    gpus = [
        dev for dev in detect_pci_devices(adapter, node)
        if dev.vendor_id == AMD_VENDOR_ID
        and dev.class_id.lower().startswith(_DISPLAY_CLASS_PREFIX)
    ]
    seen: set[str] = set()
    unique: list[PciDevice] = []
    for dev in gpus:
        if dev.function_group in seen:
            continue
        seen.add(dev.function_group)
        unique.append(dev)
    return unique


# "Bus 001 Device 004: ID 058f:6387 Alcor Micro Corp. Flash Drive"
_LSUSB_RE = re.compile(
    r"^Bus\s+\d+\s+Device\s+\d+:\s+ID\s+"
    r"(?P<id>[0-9a-fA-F]{4}:[0-9a-fA-F]{4})\s*(?P<desc>.*)$"
)

# Every host has a root hub per USB controller. They are not passable devices
# and only clutter the picker.
_ROOT_HUB_RE = re.compile(r"\broot hub\b", re.IGNORECASE)


def detect_usb_devices(adapter: ProxmoxAdapter | None = None) -> list[UsbDevice]:
    """Return the host's USB devices, newest bus order, root hubs removed.

    Addressed as ``vendor:product``. That form survives replugging into a
    different port, unlike ``bus-port``, which is the tradeoff Proxmox
    documents: identical twin devices cannot be told apart by id.
    """
    pve = adapter or get_proxmox_adapter()
    res = pve.run(["lsusb"])
    if not res.ok:
        log.debug("lsusb failed: %s", res.output)
        return []
    devices: list[UsbDevice] = []
    seen: set[str] = set()
    for line in res.output.splitlines():
        match = _LSUSB_RE.match(line.strip())
        if not match:
            continue
        device_id = match.group("id").lower()
        description = match.group("desc").strip()
        if _ROOT_HUB_RE.search(description):
            continue
        if device_id in seen:
            continue
        seen.add(device_id)
        devices.append(UsbDevice(device_id=device_id, description=description or device_id))
    return devices
