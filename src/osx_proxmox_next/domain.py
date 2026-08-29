from __future__ import annotations

import re
from dataclasses import dataclass
from shlex import join as shlex_join


SUPPORTED_MACOS = {
    "ventura": {"label": "macOS Ventura 13", "major": 13, "channel": "stable"},
    "sonoma": {"label": "macOS Sonoma 14", "major": 14, "channel": "stable"},
    "sequoia": {"label": "macOS Sequoia 15", "major": 15, "channel": "stable"},
    "tahoe": {"label": "macOS Tahoe 26", "major": 26, "channel": "stable"},
}

# Validation constants — used by domain.validate_config() and app.py form validation
MIN_VMID = 100
MAX_VMID = 999999
MIN_CORES = 2
MIN_MEMORY_MB = 4096
MIN_DISK_GB = 64
DEFAULT_VMID = 900

# Sentinel for EditChanges.gpu_device. The field is tri-state like the rest of
# the edit form, and None already means "leave it alone", so removing a card
# needs a value of its own rather than an empty string.
DETACH_DEVICE = "__detach__"

# The tool manages exactly one passed-through GPU, and it lives at hostpci0.
# Fixing the index keeps attach/detach predictable and leaves hostpci1+ free
# for anything attached by hand outside this tool.
GPU_HOSTPCI_INDEX = 0


@dataclass
class VmConfig:
    vmid: int
    name: str
    macos: str
    cores: int
    memory_mb: int
    disk_gb: int
    bridge: str
    storage: str
    installer_path: str = ""
    smbios_serial: str = ""
    smbios_uuid: str = ""
    smbios_mlb: str = ""
    smbios_rom: str = ""
    smbios_model: str = ""
    no_smbios: bool = False
    apple_services: bool = False
    vmgenid: str = ""
    static_mac: str = ""
    verbose_boot: bool = False
    iso_dir: str = ""
    cpu_model: str = ""
    net_model: str = "vmxnet3"
    vlan: int = 0  # 0 = untagged


@dataclass
class PlanStep:
    title: str
    argv: list[str]
    risk: str = "safe"

    @property
    def command(self) -> str:
        return shlex_join(self.argv)


@dataclass
class EditChanges:
    name: str | None = None
    cores: int | None = None
    memory_mb: int | None = None
    bridge: str | None = None
    disk_gb_add: int | None = None
    # NIC model used when updating bridge. None = preserve existing model from VM config.
    nic_model: str | None = None
    # Disk device name used for resize (default matches VMs created by this tool)
    disk_name: str = "virtio0"
    # Verbose boot (-v in OpenCore boot-args). Tri-state, like every other field
    # here: None leaves the VM's existing boot-args alone, True/False rewrite
    # them. Patching this means mounting the VM's OpenCore disk, so "leave it
    # alone" has to be distinguishable from "turn it off".
    verbose_boot: bool | None = None
    # GPU passthrough. None leaves hostpci0 alone, DETACH_DEVICE removes it,
    # anything else is the PCI address to attach.
    gpu_device: str | None = None
    # True marks the passed GPU as the VM's primary display (x-vga=1) and turns
    # the Proxmox console off; False keeps the console and leaves the card
    # secondary. Only read when gpu_device attaches or detaches a card.
    gpu_primary: bool = False
    # The full set of host USB devices the VM should end up with, as
    # "vendor:product" or "bus-port". None leaves every usb entry alone; an
    # empty list detaches all of them.
    usb_devices: list[str] | None = None


# A PCI address, with the 0000: domain and the .function both optional:
# qm accepts 0000:01:00.0, 01:00.0 and 01:00 (every function of the device).
_PCI_ADDRESS_RE = re.compile(r"^(?:[0-9a-fA-F]{4}:)?[0-9a-fA-F]{2}:[0-9a-fA-F]{2}(?:\.[0-9a-fA-F])?$")

# qm set -usb0 host= takes either 058f:6387 or a 2-1.2.2 bus-port path.
_USB_ID_RE = re.compile(r"^[0-9a-fA-F]{4}:[0-9a-fA-F]{4}$")
_USB_PORT_RE = re.compile(r"^\d+-\d+(?:\.\d+)*$")

# qemu-server has offered usb0..usb4 since forever; newer releases allow more,
# but five is the number every supported Proxmox version accepts.
MAX_USB_DEVICES = 5


def _validate_passthrough(changes: EditChanges) -> list[str]:
    """Return problems with the GPU/USB passthrough fields."""
    issues: list[str] = []
    gpu = changes.gpu_device
    if gpu is not None and gpu != DETACH_DEVICE and not _PCI_ADDRESS_RE.match(gpu):
        issues.append(
            f"GPU address {gpu!r} is not a PCI address "
            "(expected 01:00, 01:00.0 or 0000:01:00.0)."
        )
    usb = changes.usb_devices
    if usb is not None:
        if len(usb) > MAX_USB_DEVICES:
            issues.append(
                f"At most {MAX_USB_DEVICES} USB devices can be passed through "
                f"({len(usb)} selected)."
            )
        for device in usb:
            if not (_USB_ID_RE.match(device) or _USB_PORT_RE.match(device)):
                issues.append(
                    f"USB device {device!r} is not a device id or bus path "
                    "(expected 058f:6387 or 2-1.2.2)."
                )
        if len(set(usb)) != len(usb):
            issues.append("The same USB device is selected more than once.")
    return issues


def validate_edit_changes(vmid: int, changes: EditChanges) -> list[str]:
    issues: list[str] = []
    if vmid < MIN_VMID or vmid > MAX_VMID:
        issues.append(f"VMID must be between {MIN_VMID} and {MAX_VMID}.")
    has_any = any([
        changes.name is not None,
        changes.cores is not None,
        changes.memory_mb is not None,
        changes.bridge is not None,
        changes.disk_gb_add is not None,
        changes.verbose_boot is not None,
        changes.gpu_device is not None,
        changes.usb_devices is not None,
    ])
    if not has_any:
        issues.append("At least one change must be specified.")
    issues.extend(_validate_passthrough(changes))
    if changes.name is not None:
        if len(changes.name) < 3:
            issues.append("VM name must be at least 3 characters.")
        if len(changes.name) > 63:
            issues.append("VM name must be at most 63 characters.")
        if not re.fullmatch(r"[a-zA-Z0-9]([a-zA-Z0-9.\-]*[a-zA-Z0-9])?", changes.name):
            issues.append("VM name must start with alphanumeric and contain only [a-zA-Z0-9.-].")
    if changes.cores is not None and changes.cores < MIN_CORES:
        issues.append(f"At least {MIN_CORES} CPU cores are required.")
    if changes.memory_mb is not None and changes.memory_mb < MIN_MEMORY_MB:
        issues.append(f"At least {MIN_MEMORY_MB} MB RAM is required.")
    if changes.bridge is not None and not re.fullmatch(r"vmbr[0-9]+", changes.bridge):
        issues.append("Bridge must match vmbr<N> (e.g. vmbr0).")
    if (changes.bridge is not None and changes.nic_model is not None
            and not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]+", changes.nic_model)):
        issues.append("NIC model must be alphanumeric (e.g. vmxnet3, e1000).")
    if changes.disk_gb_add is not None and not re.fullmatch(r"(virtio|sata|scsi|ide)[0-9]+", changes.disk_name):
        issues.append("Disk name must match virtio/sata/scsi/ide followed by a number (e.g. virtio0).")
    if changes.disk_gb_add is not None and changes.disk_gb_add <= 0:
        issues.append("Disk extension must be a positive number of GB.")
    return issues


def validate_config(config: VmConfig) -> list[str]:
    issues: list[str] = []
    if config.vmid < MIN_VMID or config.vmid > MAX_VMID:
        issues.append(f"VMID must be between {MIN_VMID} and {MAX_VMID}.")
    if not config.name or len(config.name) < 3:
        issues.append("VM name must be at least 3 characters.")
    if config.name and len(config.name) > 63:
        issues.append("VM name must be at most 63 characters.")
    if config.macos not in SUPPORTED_MACOS:
        issues.append(f"macOS version must be one of: {', '.join(SUPPORTED_MACOS)}.")
    if config.cores < MIN_CORES:
        issues.append(f"At least {MIN_CORES} CPU cores are required.")
    if config.memory_mb < MIN_MEMORY_MB:
        issues.append(f"At least {MIN_MEMORY_MB} MB RAM is required.")
    if config.disk_gb < MIN_DISK_GB:
        issues.append(f"At least {MIN_DISK_GB} GB disk is required.")
    if not re.fullmatch(r"vmbr[0-9]+", config.bridge):
        issues.append("Bridge must match vmbr<N> (e.g. vmbr0).")
    if config.vlan and not (1 <= config.vlan <= 4094):
        issues.append("VLAN tag must be between 1 and 4094 (or 0 for untagged).")
    if config.name and not re.fullmatch(r"[a-zA-Z0-9]([a-zA-Z0-9.\-]*[a-zA-Z0-9])?", config.name):
        issues.append("VM name must start with alphanumeric and contain only [a-zA-Z0-9.-].")
    if config.installer_path and not re.fullmatch(r"[a-zA-Z0-9/._\-]+", config.installer_path):
        issues.append("Installer path contains invalid characters.")
    if not config.storage:
        issues.append("Storage target is required.")
    # SMBIOS fields are embedded in shell commands — restrict to safe charset
    if config.smbios_serial and not re.fullmatch(r"[A-Z0-9]{12}", config.smbios_serial):
        issues.append("SMBIOS serial must be exactly 12 chars [A-Z0-9].")
    if config.smbios_mlb and not re.fullmatch(r"[A-Z0-9]{17}", config.smbios_mlb):
        issues.append("SMBIOS MLB must be exactly 17 chars [A-Z0-9].")
    if config.smbios_rom and not re.fullmatch(r"[A-F0-9]{12}", config.smbios_rom):
        issues.append("SMBIOS ROM must be exactly 12 hex chars [A-F0-9].")
    if config.smbios_uuid and not re.fullmatch(
        r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}",
        config.smbios_uuid,
    ):
        issues.append("SMBIOS UUID must be a valid uppercase UUID.")
    if config.smbios_model and not re.fullmatch(r"[A-Za-z0-9,]{1,20}", config.smbios_model):
        issues.append("SMBIOS model must be alphanumeric (e.g., MacPro7,1).")
    if config.cpu_model and not re.fullmatch(r"[A-Za-z0-9\-]+", config.cpu_model):
        issues.append("CPU model must be alphanumeric/hyphens only (e.g., Skylake-Server-IBRS).")
    if config.net_model not in ("vmxnet3", "e1000-82545em"):
        issues.append("net_model must be 'vmxnet3' or 'e1000-82545em'.")
    if config.storage and not re.fullmatch(r"[a-zA-Z0-9_\-]+", config.storage):
        issues.append("Storage target must be alphanumeric, hyphens, underscores only.")
    if config.static_mac and not re.fullmatch(r"([0-9A-F]{2}:){5}[0-9A-F]{2}", config.static_mac):
        issues.append("Static MAC must be XX:XX:XX:XX:XX:XX format (uppercase hex).")
    if config.vmgenid and not re.fullmatch(
        r"[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}",
        config.vmgenid,
    ):
        issues.append("vmgenid must be a valid uppercase UUID.")
    return issues
