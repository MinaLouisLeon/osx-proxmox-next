from osx_proxmox_next.domain import VmConfig, validate_config


def test_validate_config_accepts_sequoia_defaults() -> None:
    cfg = VmConfig(
        vmid=900,
        name="macos-sequoia",
        macos="sequoia",
        cores=8,
        memory_mb=16384,
        disk_gb=128,
        bridge="vmbr0",
        storage="local-lvm",
    )
    assert validate_config(cfg) == []


def test_validate_config_rejects_invalid_values() -> None:
    cfg = VmConfig(
        vmid=5,
        name="x",
        macos="unknown",
        cores=1,
        memory_mb=2048,
        disk_gb=32,
        bridge="br0",
        storage="",
    )
    issues = validate_config(cfg)
    assert len(issues) >= 7
    assert any("VMID" in issue for issue in issues)
    assert any("macOS version" in issue for issue in issues)
    assert any("Bridge" in issue for issue in issues)


def test_validate_config_accepts_ventura() -> None:
    cfg = VmConfig(
        vmid=900,
        name="macos-ventura",
        macos="ventura",
        cores=4,
        memory_mb=8192,
        disk_gb=80,
        bridge="vmbr0",
        storage="local-lvm",
    )
    assert validate_config(cfg) == []


def _valid_cfg(**overrides) -> VmConfig:
    defaults = dict(
        vmid=900, name="macos-sequoia", macos="sequoia", cores=8,
        memory_mb=16384, disk_gb=128, bridge="vmbr0", storage="local-lvm",
    )
    defaults.update(overrides)
    return VmConfig(**defaults)


def test_validate_smbios_serial_valid() -> None:
    cfg = _valid_cfg(smbios_serial="C02N1000P7QM")
    assert validate_config(cfg) == []


def test_validate_smbios_serial_rejects_bad_charset() -> None:
    cfg = _valid_cfg(smbios_serial="C02';rm -rf /")
    issues = validate_config(cfg)
    assert any("serial" in i for i in issues)


def test_validate_smbios_serial_rejects_wrong_length() -> None:
    cfg = _valid_cfg(smbios_serial="SHORT")
    issues = validate_config(cfg)
    assert any("serial" in i for i in issues)


def test_validate_smbios_mlb_valid() -> None:
    cfg = _valid_cfg(smbios_mlb="C02901403QVK3F708")
    assert validate_config(cfg) == []


def test_validate_smbios_mlb_rejects_bad_charset() -> None:
    cfg = _valid_cfg(smbios_mlb="C02901403QVK3F70!")
    issues = validate_config(cfg)
    assert any("MLB" in i for i in issues)


def test_validate_smbios_rom_valid() -> None:
    cfg = _valid_cfg(smbios_rom="02ABCDEF0123")
    assert validate_config(cfg) == []


def test_validate_smbios_rom_rejects_lowercase() -> None:
    cfg = _valid_cfg(smbios_rom="02abcdef0123")
    issues = validate_config(cfg)
    assert any("ROM" in i for i in issues)


def test_validate_smbios_rom_rejects_non_hex() -> None:
    cfg = _valid_cfg(smbios_rom="02ABCDEG0123")
    issues = validate_config(cfg)
    assert any("ROM" in i for i in issues)


def test_validate_smbios_uuid_valid() -> None:
    cfg = _valid_cfg(smbios_uuid="550E8400-E29B-41D4-A716-446655440000")
    assert validate_config(cfg) == []


def test_validate_smbios_uuid_rejects_bad_format() -> None:
    cfg = _valid_cfg(smbios_uuid="not-a-uuid")
    issues = validate_config(cfg)
    assert any("UUID" in i for i in issues)


def test_validate_smbios_model_valid() -> None:
    cfg = _valid_cfg(smbios_model="MacPro7,1")
    assert validate_config(cfg) == []


def test_validate_smbios_model_rejects_injection() -> None:
    cfg = _valid_cfg(smbios_model="MacPro7,1';echo pwned")
    issues = validate_config(cfg)
    assert any("model" in i for i in issues)


def test_validate_smbios_empty_fields_ok() -> None:
    """Empty SMBIOS fields are fine — auto-generated at plan time."""
    cfg = _valid_cfg()
    assert validate_config(cfg) == []


def test_validate_tahoe_no_installer_path_ok():
    cfg = VmConfig(
        vmid=900,
        name="macos-tahoe",
        macos="tahoe",
        cores=8,
        memory_mb=16384,
        disk_gb=160,
        bridge="vmbr0",
        storage="local-lvm",
        installer_path="",
    )
    issues = validate_config(cfg)
    assert not any("Tahoe" in i for i in issues)


# ── Bridge validation ──────────────────────────────────────────────


def test_validate_bridge_rejects_non_vmbr() -> None:
    cfg = _valid_cfg(bridge="br0")
    issues = validate_config(cfg)
    assert any("Bridge" in i for i in issues)


def test_validate_bridge_rejects_vmbr_no_number() -> None:
    cfg = _valid_cfg(bridge="vmbr")
    issues = validate_config(cfg)
    assert any("Bridge" in i for i in issues)


def test_validate_bridge_accepts_vmbr1() -> None:
    cfg = _valid_cfg(bridge="vmbr1")
    assert validate_config(cfg) == []


# ── Name validation ────────────────────────────────────────────────


def test_validate_name_rejects_special_chars() -> None:
    cfg = _valid_cfg(name="macos;rm -rf /")
    issues = validate_config(cfg)
    assert any("name" in i.lower() for i in issues)


def test_validate_name_accepts_dashes_dots() -> None:
    cfg = _valid_cfg(name="macos-vm.test")
    assert validate_config(cfg) == []


# ── Installer path validation ──────────────────────────────────────


def test_validate_installer_path_rejects_shell_meta() -> None:
    cfg = _valid_cfg(installer_path="/tmp/foo;rm -rf /")
    issues = validate_config(cfg)
    assert any("path" in i.lower() for i in issues)


def test_validate_installer_path_accepts_normal() -> None:
    cfg = _valid_cfg(installer_path="/var/lib/vz/template/iso/macos.iso")
    assert validate_config(cfg) == []


# ── CPU model validation ──────────────────────────────────────────


def test_validate_cpu_model_rejects_injection() -> None:
    cfg = _valid_cfg(cpu_model="Skylake;rm")
    issues = validate_config(cfg)
    assert any("CPU" in i for i in issues)


def test_validate_cpu_model_accepts_valid() -> None:
    cfg = _valid_cfg(cpu_model="Skylake-Server-IBRS")
    assert validate_config(cfg) == []


# ── Storage validation ────────────────────────────────────────────


def test_validate_storage_rejects_injection() -> None:
    cfg = _valid_cfg(storage="local;rm")
    issues = validate_config(cfg)
    assert any("Storage" in i for i in issues)


def test_validate_storage_accepts_underscores() -> None:
    cfg = _valid_cfg(storage="wd_2tb-ssd")
    assert validate_config(cfg) == []


# ── Static MAC validation ─────────────────────────────────────────


def test_validate_static_mac_rejects_lowercase() -> None:
    cfg = _valid_cfg(static_mac="02:ab:cd:ef:01:23")
    issues = validate_config(cfg)
    assert any("MAC" in i for i in issues)


def test_validate_static_mac_accepts_valid() -> None:
    cfg = _valid_cfg(static_mac="02:AB:CD:EF:01:23")
    assert validate_config(cfg) == []


# ── vmgenid validation ────────────────────────────────────────────


def test_validate_vmgenid_rejects_bad() -> None:
    cfg = _valid_cfg(vmgenid="not-a-uuid")
    issues = validate_config(cfg)
    assert any("vmgenid" in i for i in issues)


def test_validate_vmgenid_accepts_valid() -> None:
    cfg = _valid_cfg(vmgenid="550E8400-E29B-41D4-A716-446655440000")
    assert validate_config(cfg) == []


# ── Name length validation ───────────────────────────────────────


def test_validate_name_max_length() -> None:
    cfg = _valid_cfg(name="a" * 64)
    issues = validate_config(cfg)
    assert any("63" in i for i in issues)


def test_validate_name_at_max_length_ok() -> None:
    cfg = _valid_cfg(name="a" * 63)
    assert validate_config(cfg) == []


def test_validate_config_vlan_valid_and_untagged():
    from osx_proxmox_next.domain import validate_config
    base = dict(vmid=901, name="macos-vm", macos="sequoia", cores=8,
                memory_mb=16384, disk_gb=128, bridge="vmbr0", storage="local-lvm")
    from osx_proxmox_next.domain import VmConfig
    assert validate_config(VmConfig(**base)) == []
    assert validate_config(VmConfig(**base, vlan=20)) == []
    assert validate_config(VmConfig(**base, vlan=4094)) == []


def test_validate_config_vlan_out_of_range():
    from osx_proxmox_next.domain import VmConfig, validate_config
    base = dict(vmid=901, name="macos-vm", macos="sequoia", cores=8,
                memory_mb=16384, disk_gb=128, bridge="vmbr0", storage="local-lvm")
    for bad in (4095, -3):
        issues = validate_config(VmConfig(**base, vlan=bad))
        assert any("VLAN" in i for i in issues), bad


def test_validate_edit_changes_counts_verbose_boot_as_a_change():
    """Toggling verbose boot alone is a real edit, not an empty form."""
    from osx_proxmox_next.domain import EditChanges, validate_edit_changes
    for state in (True, False):
        assert validate_edit_changes(900, EditChanges(verbose_boot=state)) == []
    issues = validate_edit_changes(900, EditChanges())
    assert any("At least one change" in i for i in issues)


def test_edit_changes_verbose_boot_defaults_to_leaving_it_alone():
    from osx_proxmox_next.domain import EditChanges
    assert EditChanges().verbose_boot is None


# ── Passthrough validation ───────────────────────────────────────────


def test_validate_edit_changes_counts_passthrough_as_a_change():
    from osx_proxmox_next.domain import DETACH_DEVICE, EditChanges, validate_edit_changes
    assert validate_edit_changes(900, EditChanges(gpu_device="01:00")) == []
    assert validate_edit_changes(900, EditChanges(gpu_device=DETACH_DEVICE)) == []
    # An empty list is "detach every USB device", which is a real change.
    assert validate_edit_changes(900, EditChanges(usb_devices=[])) == []


def test_validate_edit_changes_accepts_every_pci_address_form():
    from osx_proxmox_next.domain import EditChanges, validate_edit_changes
    for address in ("01:00", "01:00.0", "0000:01:00", "0000:01:00.0", "ff:1f.7"):
        assert validate_edit_changes(900, EditChanges(gpu_device=address)) == [], address


def test_validate_edit_changes_rejects_a_bad_pci_address():
    from osx_proxmox_next.domain import EditChanges, validate_edit_changes
    for address in ("bogus", "01", "gg:00", "01:00.0.0", ""):
        issues = validate_edit_changes(900, EditChanges(gpu_device=address))
        assert any("PCI address" in i for i in issues), address


def test_validate_edit_changes_accepts_both_usb_address_forms():
    from osx_proxmox_next.domain import EditChanges, validate_edit_changes
    assert validate_edit_changes(
        900, EditChanges(usb_devices=["058f:6387", "2-1.2.2", "1-4"])) == []


def test_validate_edit_changes_rejects_a_bad_usb_id():
    from osx_proxmox_next.domain import EditChanges, validate_edit_changes
    issues = validate_edit_changes(900, EditChanges(usb_devices=["not-a-device"]))
    assert any("USB device" in i for i in issues)


def test_validate_edit_changes_caps_the_usb_count():
    from osx_proxmox_next.domain import MAX_USB_DEVICES, EditChanges, validate_edit_changes
    too_many = [f"058f:{i:04d}" for i in range(MAX_USB_DEVICES + 1)]
    issues = validate_edit_changes(900, EditChanges(usb_devices=too_many))
    assert any(f"At most {MAX_USB_DEVICES}" in i for i in issues)


def test_validate_edit_changes_rejects_a_duplicated_usb_device():
    """Two slots cannot hold the same host device."""
    from osx_proxmox_next.domain import EditChanges, validate_edit_changes
    issues = validate_edit_changes(900, EditChanges(usb_devices=["058f:6387", "058f:6387"]))
    assert any("more than once" in i for i in issues)


def test_edit_changes_passthrough_defaults_leave_devices_alone():
    from osx_proxmox_next.domain import EditChanges
    changes = EditChanges()
    assert changes.gpu_device is None
    assert changes.usb_devices is None
    assert changes.gpu_primary is False
