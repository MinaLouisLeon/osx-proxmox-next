from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..domain import DEFAULT_VMID, PlanStep, VmConfig
from ..preflight import PreflightCheck
from ..rollback import RollbackSnapshot
from ..smbios import SmbiosIdentity

__all__ = ["WizardState"]


@dataclass
class WizardState:
    selected_os: str = ""
    selected_storage: str = ""
    storage_targets: list[str] = field(default_factory=list)
    iso_dirs: list[str] = field(default_factory=list)
    selected_iso_dir: str = ""
    # Form
    vmid: int = DEFAULT_VMID
    name: str = ""
    cores: int = 8
    # Last core count the wizard filled in itself, and whether the user has
    # since typed their own. Auto-fills never overwrite a manual choice.
    cores_auto: str = ""
    cores_user_set: bool = False
    memory_mb: int = 16384
    disk_gb: int = 128
    bridge: str = "vmbr0"
    storage: str = "local-lvm"
    installer_path: str = ""
    smbios: SmbiosIdentity | None = None
    apple_services: bool = False
    use_penryn: bool = False
    unattended: bool = False
    verbose_boot: bool = False
    net_model: str = "vmxnet3"
    form_errors: dict[str, str] = field(default_factory=dict)
    # Preflight
    preflight_done: bool = False
    preflight_ok: bool = False
    preflight_checks: list[PreflightCheck] = field(default_factory=list)
    # Downloads
    download_running: bool = False
    download_phase: str = ""
    download_pct: int = 0
    download_errors: list[str] = field(default_factory=list)
    downloads_complete: bool = False
    # Config + Plan
    config: VmConfig | None = None
    plan_steps: list[PlanStep] = field(default_factory=list)
    assets_ok: bool = False
    assets_missing: list[str] = field(default_factory=list)
    # Dry run
    dry_run_done: bool = False
    dry_run_ok: bool = False
    apply_running: bool = False
    apply_log: list[str] = field(default_factory=list)  # legacy alias kept for compat
    dry_log: list[str] = field(default_factory=list)
    live_log_lines: list[str] = field(default_factory=list)
    # Live install
    live_done: bool = False
    live_ok: bool = False
    live_log: Path | None = None
    snapshot: RollbackSnapshot | None = None
    # Manage mode
    manage_mode: bool = False
    uninstall_vm_list: list[str] = field(default_factory=list)
    uninstall_purge: bool = True
    uninstall_log: list[str] = field(default_factory=list)
    uninstall_running: bool = False
    uninstall_done: bool = False
    uninstall_ok: bool = False
    # Edit mode
    edit_running: bool = False
    edit_done: bool = False
    edit_ok: bool = False
    edit_log: list[str] = field(default_factory=list)
    edit_start_after: bool = False
    # Host devices offered for passthrough, scanned once per Manage visit.
    edit_devices_loaded: bool = False
    edit_host_gpus: list = field(default_factory=list)
    edit_host_usb: list = field(default_factory=list)
    # What the VM in the box already has. edit_loaded_vmid guards against a
    # slow scan landing after the user has typed a different VMID.
    edit_loaded_vmid: int | None = None
    edit_current_gpu: str = ""
    edit_current_usb: list[str] = field(default_factory=list)
    # False until the VM's config has actually been read. Until then an empty
    # tick list means "unknown", not "detach everything".
    edit_usb_known: bool = False
