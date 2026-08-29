from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    ProgressBar,
    Select,
    SelectionList,
    Static,
)

from ..defaults import (
    DEFAULT_BRIDGE,
    DEFAULT_ISO_DIR,
    DEFAULT_MEMORY_MB,
    DEFAULT_STORAGE,
    CpuInfo,
    core_choices,
    max_vm_cores,
    recommended_cores,
)
from ..domain import DEFAULT_VMID, DETACH_DEVICE, SUPPORTED_MACOS

# Every field in the Edit VM panel is leave-blank-to-keep, and the panel never
# loads the VM's current settings, so a plain checkbox could not say "don't
# touch it" -- unticked would be indistinguishable from "turn it off". Rewriting
# boot-args means mounting the VM's OpenCore disk, so that distinction has to
# survive: keeping is the default and costs nothing.
VERBOSE_BOOT_KEEP = "keep"
VERBOSE_BOOT_EDIT_CHOICES = [
    ("Keep unchanged", VERBOSE_BOOT_KEEP),
    ("Enable (-v)", "on"),
    ("Disable", "off"),
]

# The GPU picker follows the same leave-it-alone-by-default rule, but it is the
# one select whose options are replaced once the host scan finishes, and
# Select.set_options() resets the value to Select.BLANK. So "keep" is the blank
# state here rather than an option of its own: rebuilding the list then lands on
# "leave it alone" by construction instead of raising on a select that forbids
# blank.
GPU_KEEP_PROMPT = "Keep unchanged"
GPU_DETACH_CHOICE = ("Detach GPU (hostpci0)", DETACH_DEVICE)

# One control, not two: x-vga=1 is exactly the thing that takes the Proxmox
# console away, so the console is what the user picks and x-vga follows.
CONSOLE_KEEP_VNC = "vnc"
CONSOLE_GPU_PRIMARY = "primary"
CONSOLE_CHOICES = [
    ("Keep working (VNC)", CONSOLE_KEEP_VNC),
    ("Disable, GPU is primary", CONSOLE_GPU_PRIMARY),
]


def gpu_choices(devices) -> list[tuple[str, str]]:
    """Return the GPU dropdown entries for the detected *devices*.

    "Keep unchanged" is not in here: it is the select's blank prompt.
    """
    return [(dev.label, dev.function_group) for dev in devices] + [GPU_DETACH_CHOICE]


def gpu_hint_text(detected: int, current: str) -> str:
    """Return the line under the GPU picker: what is attached, what was found."""
    attached = f"Attached now: {current}." if current else "Nothing attached to hostpci0."
    if detected:
        found = f" {detected} AMD GPU(s) found on this host."
    else:
        found = (
            " No AMD GPU detected - macOS has no driver for NVIDIA, so only AMD "
            "cards are offered. Type an address below to pass something else."
        )
    return attached + found

__all__ = [
    "CONSOLE_CHOICES",
    "CONSOLE_GPU_PRIMARY",
    "CONSOLE_KEEP_VNC",
    "GPU_DETACH_CHOICE",
    "GPU_KEEP_PROMPT",
    "VERBOSE_BOOT_EDIT_CHOICES",
    "VERBOSE_BOOT_KEEP",
    "gpu_choices",
    "gpu_hint_text",
    "usb_hint_text",
    "cores_hint_text",
    "compose_step1",
    "compose_step2",
    "compose_step3",
    "compose_step4",
    "compose_step5",
    "compose_step6",
]


def usb_hint_text(detected: int) -> str:
    """Return the line under the USB list."""
    if not detected:
        return (
            "No USB devices found on the host (lsusb unavailable or nothing "
            "attached). Type ids below to pass devices anyway."
        )
    return (
        f"{detected} device(s) on this host. Ticked devices are attached to the VM, "
        "unticked ones are detached from it - the list starts out matching the VM."
    )


def compose_step1() -> ComposeResult:
    with Vertical(id="step1", classes="step_container"):
        yield Static("Host Preflight Checks")
        yield Static("Checking...", id="preflight_checks")
        with Horizontal(classes="nav_row"):
            yield Button("Continue", id="preflight_next_btn", disabled=True)
            yield Button("Exit", id="exit_btn")


def compose_step2() -> ComposeResult:
    with Vertical(id="step2", classes="step_container step_hidden"):
        with Horizontal(classes="action_row"):
            yield Button("Create VM", id="mode_create", classes="mode_btn mode_active")
            yield Button("Manage VMs", id="mode_manage", classes="mode_btn")
        # Create panel
        with Vertical(id="create_panel"):
            yield Static("Choose macOS Version")
            with Horizontal(id="os_cards"):
                for key, meta in SUPPORTED_MACOS.items():
                    channel = "STABLE" if meta["channel"] == "stable" else "PREVIEW"
                    yield Button(
                        f"{meta['label']}\n{channel}",
                        id=f"os_{key}",
                        classes="os_card",
                    )
            with Horizontal(classes="nav_row"):
                yield Button("Back", id="back_btn_2")
                yield Button("Next", id="next_btn", disabled=True)
                yield Button("Exit", id="exit_btn_2")
        # Manage panel
        with Vertical(id="manage_panel", classes="hidden"):
            yield Static("Manage VMs")
            yield Static("", id="vm_list_display")
            with Horizontal(classes="action_row"):
                yield Button("Refresh List", id="manage_refresh_btn")
            yield Static("Enter the VM ID to remove:", id="manage_vmid_label")
            yield Input(value="", id="manage_vmid", placeholder="e.g. 106")
            with Horizontal(classes="action_row"):
                yield Checkbox("Delete disk images", value=True, id="manage_purge_cb")
                yield Button("Remove VM", id="manage_destroy_btn", disabled=True)
            yield Static(
                "This will stop the VM, remove its configuration,\n"
                "and delete all associated disk images.",
                id="manage_hint",
                classes="hint",
            )
            yield Static("", id="manage_log", classes="hidden")
            yield Static("", id="manage_result", classes="hidden")
            # ── Edit VM ──────────────────────────────────────────────
            yield Static("Edit VM", classes="manage_section_header")
            yield Static("VM ID to edit:", id="edit_vmid_label")
            yield Input(value="", id="edit_vmid", placeholder="e.g. 106")
            with Vertical(id="edit_form", classes="hidden"):
                with Container(id="edit_grid"):
                    yield Static("Name", classes="label")
                    yield Input(value="", id="edit_name", placeholder="leave blank to keep")
                    yield Static("CPU Cores", classes="label")
                    yield Input(value="", id="edit_cores", placeholder="leave blank to keep")
                    yield Static("Memory MB", classes="label")
                    yield Input(value="", id="edit_memory", placeholder="leave blank to keep")
                    yield Static("Bridge", classes="label")
                    yield Input(value="", id="edit_bridge", placeholder="leave blank to keep")
                    yield Static("NIC Model", classes="label")
                    yield Input(value="", id="edit_nic_model", placeholder="leave blank to preserve existing")
                    yield Static("Add Disk GB", classes="label")
                    yield Input(value="", id="edit_disk_add", placeholder="GB to add, e.g. 64")
                    yield Static("Disk Name", classes="label")
                    yield Input(value="", id="edit_disk_name", placeholder="leave blank for virtio0")
                    yield Static("Verbose Boot", classes="label")
                    yield Select(
                        VERBOSE_BOOT_EDIT_CHOICES,
                        value=VERBOSE_BOOT_KEEP,
                        allow_blank=False,
                        id="edit_verbose_boot",
                    )
                yield from _compose_edit_passthrough()
                with Horizontal(classes="action_row"):
                    yield Checkbox("Start VM after", value=False, id="edit_start_after_cb")
                    yield Button("Apply Changes", id="edit_apply_btn", disabled=True)
            yield Static("", id="edit_log", classes="hidden")
            yield Static("", id="edit_result", classes="hidden")
            # The wizard's Exit buttons all live in the Create panel, which is
            # hidden while managing, so finishing an edit left the keyboard
            # bindings as the only way out. Give Manage its own way to close.
            with Horizontal(classes="nav_row"):
                yield Button("Exit", id="exit_btn_manage")


def compose_step3(storage_targets: list[str]) -> ComposeResult:
    with Vertical(id="step3", classes="step_container step_hidden"):
        yield Static("Choose Storage Target")
        with Horizontal(id="storage_row"):
            for idx, target in enumerate(storage_targets):
                cls = "storage_btn storage_selected" if idx == 0 else "storage_btn"
                yield Button(target, id=f"storage_{idx}", classes=cls)
        with Horizontal(classes="nav_row"):
            yield Button("Back", id="back_btn_3")
            yield Button("Next", id="next_btn_3")
            yield Button("Exit", id="exit_btn_3")


def cores_hint_text(host_cores: int | None = None) -> str:
    """One-line help under the CPU Cores field: what is allowed on this host."""
    limit = host_cores if host_cores and host_cores > 0 else max_vm_cores()
    allowed = ", ".join(str(n) for n in core_choices(limit))
    return f"Editable - power of 2 only ({allowed}); host has {limit} logical CPUs"


def _compose_edit_passthrough() -> ComposeResult:
    """Yield the GPU and USB passthrough controls for the Edit VM panel.

    The device lists start empty and are filled in from the host once the
    Manage tab is opened -- running lspci/pvesh during compose would put a
    hardware scan in front of every startup, including for people who never
    open this panel.
    """
    yield Static("Host device passthrough", classes="manage_section_header")
    with Container(id="edit_passthrough_grid"):
        yield Static("GPU (hostpci0)", classes="label")
        yield Select(gpu_choices([]), prompt=GPU_KEEP_PROMPT, id="edit_gpu")
        yield Static("", classes="label")
        yield Static(gpu_hint_text(0, ""), id="edit_gpu_hint", classes="field_hint")
        yield Static("Or PCI address", classes="label")
        yield Input(value="", id="edit_gpu_address", placeholder="e.g. 01:00 - overrides the list above")
        yield Static("Proxmox console", classes="label")
        yield Select(
            CONSOLE_CHOICES, value=CONSOLE_KEEP_VNC, allow_blank=False, id="edit_console",
        )
        yield Static("", classes="label")
        yield Static(
            "Disabling the console sets x-vga=1 and vga: none. If macOS cannot drive "
            "the card you get a black screen with no VNC to fall back on.",
            id="edit_console_hint", classes="field_hint",
        )
    yield Static("USB devices (ticked = passed through)", classes="manage_section_header")
    yield SelectionList(id="edit_usb_list")
    yield Static(usb_hint_text(0), id="edit_usb_hint", classes="hint")
    with Container(id="edit_usb_manual_grid"):
        yield Static("Or USB ids", classes="label")
        yield Input(value="", id="edit_usb_manual", placeholder="058f:6387, 2-1.2.2 - comma separated")


def _compose_step4_vm_fields(use_penryn: bool = False) -> ComposeResult:
    """Yield the basic VM configuration input grid."""
    with Container(id="config_grid"):
        yield Static("VMID", classes="label")
        yield Input(value=str(DEFAULT_VMID), id="vmid")
        yield Static("VM Name", classes="label")
        yield Input(value="", id="name")
        yield Static("CPU Cores", classes="label")
        yield Input(value=str(recommended_cores(use_penryn)), id="cores")
        yield Static("", classes="label")
        yield Static(cores_hint_text(), id="cores_hint", classes="field_hint")
        yield Static("Memory MB", classes="label")
        yield Input(value=str(DEFAULT_MEMORY_MB), id="memory")
        yield Static("Disk GB", classes="label")
        yield Input(value="128", id="disk")
        yield Static("Bridge", classes="label")
        yield Input(value=DEFAULT_BRIDGE, id="bridge")
        yield Static("VLAN Tag (optional)", classes="label")
        yield Input(value="", id="vlan", placeholder="Untagged")
        yield Static("Storage", classes="label")
        yield Input(value=DEFAULT_STORAGE, id="storage_input")
        yield Static("ISO Storage", classes="label")
        yield Input(value=DEFAULT_ISO_DIR, id="iso_dir")
        yield Static("Installer Path", classes="label")
        yield Input(value="", id="installer_path")
        yield Static("Existing UUID (optional)", classes="label")
        yield Input(value="", id="existing_uuid", placeholder="Preserve existing VM UUID")


def _compose_step4_cpu_network(cpu_info: CpuInfo) -> ComposeResult:
    """Yield CPU mode and network adapter checkboxes with their hint statics."""
    with Horizontal(classes="action_row"):
        yield Checkbox(
            "Use Penryn CPU mode (recommended for older Intel CPUs)",
            id="penryn_cb",
            value=cpu_info.needs_penryn,
        )
    yield Static(
        "Older Intel CPU detected (pre-Skylake). Penryn mode improves macOS install stability on this hardware. (Xeon CPUs are automatically excluded - they use -cpu host.)",
        id="penryn_hint",
        classes="penryn_hint" + ("" if cpu_info.needs_penryn else " step_hidden"),
    )
    _e1000_default = cpu_info.is_xeon or cpu_info.needs_penryn
    with Horizontal(classes="action_row"):
        yield Checkbox(
            "Use e1000 network adapter (recommended for Xeon / older Intel - no kext needed)",
            id="e1000_cb",
            value=_e1000_default,
        )
    yield Static(
        "Xeon or legacy Intel CPU detected. e1000 has a native macOS driver and avoids slow recovery downloads caused by vmxnet3 kext not loading during install.",
        id="e1000_hint",
        classes="penryn_hint" + ("" if _e1000_default else " step_hidden"),
    )


def _compose_step4_apple_services() -> ComposeResult:
    """Yield Apple services checkbox and its conditional fields."""
    with Horizontal(classes="action_row"):
        yield Checkbox("Enable Apple Services (iMessage, FaceTime, iCloud)", id="apple_services_cb")
    with Container(id="apple_services_fields", classes="hidden"):
        yield Static("Custom vmgenid (optional)", classes="label")
        yield Input(value="", id="custom_vmgenid", placeholder="Auto-generated if empty")
        yield Static("Custom MAC (optional)", classes="label")
        yield Input(value="", id="custom_mac", placeholder="Auto-generated if empty")


def _compose_step4_verbose_boot() -> ComposeResult:
    """Yield the verbose-boot checkbox with its hint."""
    with Horizontal(classes="action_row"):
        yield Checkbox(
            "Verbose boot (-v) - show the kernel log instead of the Apple logo",
            id="verbose_boot_cb",
        )
    yield Static(
        "Adds -v to OpenCore's boot-args. Leave it off for a normal-looking boot; "
        "turn it on to see where a boot hangs. You can flip it later on an "
        "installed VM from Manage > Edit VM.",
        id="verbose_boot_hint", classes="hint",
    )


def _compose_step4_unattended() -> ComposeResult:
    """Yield the unattended-install (beta) checkbox with its warning hint."""
    with Horizontal(classes="action_row"):
        yield Checkbox("Unattended install (BETA) - hands-off until Setup Assistant", id="unattended_cb")
    yield Static(
        "Drives the whole install over the VM console: boots recovery, ERASES the "
        "new VM disk, runs the installer, and handles every reboot. Verified on "
        "Ventura, Sonoma, Sequoia, and Tahoe. Leave the VM alone while it runs.",
        id="unattended_hint", classes="hint",
    )


def compose_step4(cpu_info: CpuInfo) -> ComposeResult:
    with Vertical(id="step4", classes="step_container step_hidden"):
        yield Static("VM Configuration")
        yield from _compose_step4_vm_fields(cpu_info.needs_penryn)
        yield from _compose_step4_apple_services()
        yield from _compose_step4_cpu_network(cpu_info)
        yield from _compose_step4_verbose_boot()
        yield from _compose_step4_unattended()
        yield Static("", id="form_errors")
        with Horizontal(classes="action_row"):
            yield Button("Suggest Defaults", id="suggest_btn")
            yield Button("Generate SMBIOS", id="smbios_btn")
        yield Static("SMBIOS: not generated yet.", id="smbios_preview")
        with Horizontal(classes="nav_row"):
            yield Button("Back", id="back_btn_4")
            yield Button("Next", id="next_btn_4")
            yield Button("Exit", id="exit_btn_4")


def compose_step5() -> ComposeResult:
    with Vertical(id="step5", classes="step_container step_hidden"):
        yield Static("Review & Dry Run")
        yield Static("", id="config_summary")
        yield Static("", id="download_status")
        yield Checkbox("Force fresh download (ignore cached ISO)", value=False, id="force_download_cb")
        yield Static(
            "Re-fetches the OpenCore image. Does not modify any existing VM.",
            id="force_download_hint", classes="hint",
        )
        yield ProgressBar(total=100, show_eta=False, id="download_progress", classes="hidden")
        with Horizontal(classes="action_row"):
            yield Button("Run Dry Apply", id="dry_run_btn", disabled=True)
        yield ProgressBar(total=1, show_eta=False, id="dry_progress", classes="hidden")
        yield Static("", id="dry_log", classes="hidden")
        with Horizontal(classes="nav_row"):
            yield Button("Back", id="back_btn_5")
            yield Button("Next: Install", id="next_btn_5", disabled=True)
            yield Button("Exit", id="exit_btn_5")


def compose_step6() -> ComposeResult:
    with Vertical(id="step6", classes="step_container step_hidden"):
        yield Static("Install macOS")
        yield Button("Install", id="install_btn", classes="hidden")
        yield ProgressBar(total=1, show_eta=False, id="live_progress", classes="hidden")
        yield Static("", id="live_log", classes="hidden")
        yield Static("", id="result_box", classes="hidden")
        with Horizontal(classes="nav_row"):
            yield Button("Back", id="back_btn_6")
            yield Button("Exit", id="exit_btn_6")
