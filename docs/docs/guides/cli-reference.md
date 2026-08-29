---
sidebar_position: 2
title: CLI Reference
---

# CLI Reference

The CLI (`osx-next-cli`) provides non-interactive, scriptable VM management. It bypasses the TUI entirely.

```bash
osx-next-cli --version
```

## Subcommands

| Subcommand | Description |
|------------|-------------|
| `apply` | Create a macOS VM (dry-run by default, `--execute` to run) |
| `plan` | Preview the command plan without creating anything |
| `edit` | Modify an existing macOS VM (stop, apply changes, optionally restart) |
| `download` | Download OpenCore and recovery images |
| `preflight` | Check host readiness |
| `status` | Show info about an existing VM |
| `uninstall` | Destroy an existing VM |
| `clone` | Clone a VM with a fresh SMBIOS identity |
| `bundle` | Export diagnostic log bundle |
| `guide` | Show recovery guide for a given issue |
| `doctor` | Diagnose a running or stopped macOS VM for common config issues |
| `post-install` | Detach recovery and switch to OpenCore-first boot order |
| `install-unattended` | (Beta) Drive the whole macOS install over the VM console |

## Common Flags

These flags are shared by `apply` and `plan`:

| Flag | Type | Required | Description |
|------|------|----------|-------------|
| `--vmid` | int | Yes | VM ID (100-999999) |
| `--name` | string | Yes | VM display name |
| `--macos` | string | Yes | Target version: `ventura`, `sonoma`, `sequoia`, `tahoe` |
| `--cores` | int | Yes | CPU cores (power of 2) |
| `--memory` | int | Yes | RAM in MB (minimum 4096) |
| `--disk` | int | Yes | Disk size in GB (minimum 64) |
| `--bridge` | string | Yes | Network bridge (e.g., `vmbr0`) |
| `--storage` | string | Yes | Proxmox storage target (e.g., `local-lvm`) |
| `--iso-dir` | string | No | Custom directory for ISO/recovery images |
| `--vlan` | int | No | VLAN tag for `net0` (1-4094; `0` or omitted = untagged) |
| `--cpu-model` | string | No | Override QEMU CPU model (default: auto-detect) |
| `--net-model` | string | No | NIC model: `vmxnet3` or `e1000-82545em` (default: auto-detect) |
| `--apple-services` | flag | No | Enable iCloud/iMessage/FaceTime support |
| `--verbose-boot` | flag | No | Show kernel log instead of Apple logo |
| `--no-smbios` | flag | No | Skip SMBIOS generation entirely |
| `--no-download` | flag | No | Skip auto-download of missing assets |
| `--smbios-serial` | string | No | Custom serial number |
| `--smbios-uuid` | string | No | Custom UUID |
| `--smbios-mlb` | string | No | Custom MLB (Main Logic Board) |
| `--smbios-rom` | string | No | Custom ROM value |
| `--smbios-model` | string | No | Custom Mac model (e.g., `MacPro7,1`) |
| `--installer-path` | string | No | Path to installer image |

## edit -- Flags

| Flag | Type | Required | Description |
|------|------|----------|-------------|
| `--vmid` | int | Yes | VM ID to modify |
| `--name` | string | No | New VM display name |
| `--cores` | int | No | New CPU core count |
| `--memory` | int | No | New RAM in MB |
| `--bridge` | string | No | New network bridge (e.g. `vmbr1`) |
| `--add-disk` | int | No | Extend the target disk by N GB |
| `--disk-name` | string | No | Disk device to resize (default: `virtio0`) |
| `--nic-model` | string | No | NIC model when updating bridge (default: preserve existing) |
| `--verbose-boot` | flag | No | Turn verbose boot on (adds `-v` to OpenCore boot-args) |
| `--no-verbose-boot` | flag | No | Turn verbose boot off (removes `-v`) |
| `--gpu` | string | No | Pass a GPU through at `hostpci0` (e.g. `01:00`), or `detach` to remove it |
| `--gpu-primary` | flag | No | Make the passed GPU primary (`x-vga=1`) and set `vga: none` |
| `--usb` | string | No | Comma-separated USB devices the VM should end up with; unlisted ones are detached |
| `--start` | flag | No | Start VM after changes are applied |
| `--execute` | flag | No | Actually run (default is dry run) |

At least one change flag (`--name`, `--cores`, `--memory`, `--bridge`, `--add-disk`, `--verbose-boot`/`--no-verbose-boot`, `--gpu`, `--usb`) is required.

`--verbose-boot` and `--no-verbose-boot` are mutually exclusive. Omit both and the VM's existing boot-args are left untouched -- there is no default that silently resets them.

## clone -- Flags

| Flag | Type | Required | Description |
|------|------|----------|-------------|
| `--source-vmid` | int | Yes | VMID of the VM to clone (100-999999) |
| `--new-vmid` | int | Yes | VMID for the cloned VM (must differ from source) |
| `--name` | string | No | Display name for the clone (3-63 chars, alphanumeric/dot/hyphen) |
| `--macos` | string | No | macOS version hint for SMBIOS model selection (default: `sequoia`) |
| `--no-apple-services` | flag | No | Skip vmgenid and MAC regeneration (not recommended) |
| `--execute` | flag | No | Actually run (default is dry run) |

Without `--no-apple-services` (the default), the clone step regenerates serial, UUID, MLB, ROM, vmgenid, and MAC address so both VMs remain fully independent on iCloud, iMessage, and FaceTime.

## plan -- Flags

These flags apply only to the `plan` subcommand:

| Flag | Type | Description |
|------|------|-------------|
| `--json` | flag | Output the plan as JSON (useful for scripting and CI) |
| `--script-out` | string | Write the plan as an executable shell script to the given path |

## Usage Examples

### apply -- Create a VM

Dry-run (preview commands):

```bash
osx-next-cli apply \
  --vmid 910 --name macos-sequoia --macos sequoia \
  --cores 8 --memory 16384 --disk 128 \
  --bridge vmbr0 --storage local-lvm
```

Execute for real:

```bash
osx-next-cli apply --execute \
  --vmid 910 --name macos-sequoia --macos sequoia \
  --cores 8 --memory 16384 --disk 128 \
  --bridge vmbr0 --storage local-lvm
```

With verbose boot:

```bash
osx-next-cli apply --execute --verbose-boot \
  --vmid 910 --name macos-sequoia --macos sequoia \
  --cores 8 --memory 16384 --disk 128 \
  --bridge vmbr0 --storage local-lvm
```

### plan -- Preview the Plan

Human-readable output:

```bash
osx-next-cli plan \
  --vmid 910 --name macos-sequoia --macos sequoia \
  --cores 8 --memory 16384 --disk 128 \
  --bridge vmbr0 --storage local-lvm
```

JSON output (for scripting/CI):

```bash
osx-next-cli plan --json \
  --vmid 910 --name macos-sequoia --macos sequoia \
  --cores 8 --memory 16384 --disk 128 \
  --bridge vmbr0 --storage local-lvm
```

Export as shell script:

```bash
osx-next-cli plan --script-out ./create-vm.sh \
  --vmid 910 --name macos-sequoia --macos sequoia \
  --cores 8 --memory 16384 --disk 128 \
  --bridge vmbr0 --storage local-lvm
```

### download -- Fetch Assets

```bash
# Download both OpenCore and recovery
osx-next-cli download --macos ventura

# OpenCore only
osx-next-cli download --macos sonoma --opencore-only

# Recovery only, custom destination
osx-next-cli download --macos sequoia --recovery-only --dest /mnt/pve/nas/template/iso
```

### preflight -- Check Host

```bash
osx-next-cli preflight
```

Outputs OK/FAIL for each host check. Automatically installs missing build dependencies if detected.

### status -- Query a VM

```bash
osx-next-cli status --vmid 910
```

Shows VM name, status, and key config values (cores, memory, CPU model, network, SMBIOS).

### uninstall -- Destroy a VM

Dry-run (preview):

```bash
osx-next-cli uninstall --vmid 910
```

Execute with disk cleanup:

```bash
osx-next-cli uninstall --vmid 910 --purge --execute
```

### edit -- Modify an Existing VM

Dry-run (preview what will change):

```bash
osx-next-cli edit --vmid 910 --cores 4 --memory 8192
```

Execute for real:

```bash
osx-next-cli edit --vmid 910 --cores 4 --memory 8192 --execute
```

Rename a VM and extend its disk:

```bash
osx-next-cli edit --vmid 910 --name macos-sequoia-v2 --add-disk 64 --execute
```

Change network bridge (preserves existing NIC model and MAC):

```bash
osx-next-cli edit --vmid 910 --bridge vmbr1 --execute
```

Change bridge with an explicit NIC model:

```bash
osx-next-cli edit --vmid 910 --bridge vmbr1 --nic-model e1000 --execute
```

Apply changes and restart the VM automatically:

```bash
osx-next-cli edit --vmid 910 --cores 8 --memory 16384 --start --execute
```

Turn verbose boot on for an already-installed VM, then off again:

```bash
osx-next-cli edit --vmid 910 --verbose-boot --execute
osx-next-cli edit --vmid 910 --no-verbose-boot --execute
```

This mounts the VM's OpenCore disk and rewrites `boot-args` in `config.plist`,
adding or removing `-v` while leaving the rest of the arguments alone. The VM
must be stopped, which `edit` does for you. Any other edit leaves `boot-args`
untouched, so changing the core count never quietly turns verbose boot off.

### Passing host devices through

Attach a GPU. The address is written without its function, so every function of
the card goes through -- the GPU and its HDMI audio together, which is what
macOS expects:

```bash
osx-next-cli edit --vmid 910 --gpu 01:00 --execute
```

That leaves `vga: std`, so the Proxmox console still works and you can watch the
VM boot over VNC. To make the card the VM's primary display instead:

```bash
osx-next-cli edit --vmid 910 --gpu 01:00 --gpu-primary --execute
```

`--gpu-primary` adds `x-vga=1` and sets `vga: none`. That is the setup you want
with a monitor plugged into the card, but it removes the VNC console: if macOS
cannot drive the GPU you get a black screen and no way in. Detaching gives the
console back:

```bash
osx-next-cli edit --vmid 910 --gpu detach --execute
```

`--usb` takes the full set of devices the VM should end up with, not a list to
add. Anything attached but not listed is detached, which is how you remove one:

```bash
osx-next-cli edit --vmid 910 --usb 058f:6387,046d:c52b --execute   # exactly these two
osx-next-cli edit --vmid 910 --usb 058f:6387 --execute             # drops the Logitech
osx-next-cli edit --vmid 910 --usb "" --execute                    # detaches all of them
```

Devices are addressed as `vendor:product` (from `lsusb`) or as a `2-1.2.2`
bus-port path. Up to five can be passed at once. Run `lspci -nn` and `lsusb` on
the host to find addresses, or use the TUI, which lists them for you.

:::warning
PCI passthrough needs host-side setup first -- IOMMU on the kernel cmdline and
the GPU bound to `vfio-pci`. `edit` attaches the device to the VM; it does not
prepare the host. See [GPU Passthrough](#gpu-passthrough-prerequisites) below.
:::

### GPU Passthrough prerequisites

Before any of the above will work:

1. Enable **VT-d / IOMMU** in BIOS/UEFI
2. Add to the kernel cmdline -- Intel: `intel_iommu=on iommu=pt`, AMD: `amd_iommu=on iommu=pt`
3. Bind the GPU and its audio function to `vfio-pci`
4. Reboot the host

`osx-next-cli preflight` reports whether IOMMU is enabled. Only AMD cards are
offered in the TUI picker: macOS has had no NVIDIA driver since High Sierra.

:::note
The `edit` subcommand always stops the VM before making changes. A config snapshot is saved to `generated/snapshots/` before any modifications. On failure, rollback hints are printed so you can restore manually.
:::

### clone -- Clone a VM with Fresh Identity

Cloning a macOS VM on Proxmox duplicates its SMBIOS — both VMs share the same serial number, UUID, and MLB, which causes Apple to block both from iCloud, iMessage, and FaceTime. The `clone` subcommand handles this automatically.

Dry-run (preview commands):

```bash
osx-next-cli clone --source-vmid 910 --new-vmid 911 --name macos-sequoia-clone
```

Execute for real:

```bash
osx-next-cli clone --source-vmid 910 --new-vmid 911 --name macos-sequoia-clone --execute
```

With explicit macOS version hint:

```bash
osx-next-cli clone --source-vmid 910 --new-vmid 911 --macos sonoma --execute
```

Without Apple services identity reset (not recommended):

```bash
osx-next-cli clone --source-vmid 910 --new-vmid 911 --no-apple-services --execute
```

:::note
The clone always performs a full disk copy (`qm clone --full`). The bridge and NIC model are preserved from the source VM. The new VM gets a fresh serial, UUID, MLB, ROM, vmgenid, and MAC address.
:::

### bundle -- Export Diagnostics

```bash
osx-next-cli bundle
```

Exports a log bundle for troubleshooting.

### guide -- Recovery Guide

```bash
osx-next-cli guide "boot issue"
```

Prints recovery steps for the given issue description.

Prints recovery steps for the given issue description.

### doctor -- Diagnose VM Configuration

```bash
osx-next-cli doctor --vmid 910
```

Runs checks against a VM's configuration to detect issues that prevent macOS from booting or functioning properly.

| Check | Severity | Description |
|-------|----------|-------------|
| `balloon` | FAIL | Must be `0` — macOS has no balloon driver |
| `machine` | FAIL | Must include `q35` — UEFI chipset required |
| `cores` | FAIL/WARN | Non-power-of-2 values cause hangs at Apple logo |
| `memory` | WARN | Should be ≥4096 MB for installer |
| `cpu` | WARN | Should be `host` or `Cascadelake-Server` |
| `net0` | FAIL | Must use `vmxnet3`, `e1000`, or `e1000-82545em` |
| `agent` | WARN | Should be `enabled=1` for graceful shutdown |
| `smbios1` | WARN | Must contain `uuid=` for Apple services |
| `boot` | FAIL | Must not reference `ide3` (non-existent device) |
| `virtio0` | WARN | Main macOS disk should be present |
| `ide0` | WARN | OpenCore bootloader disk should be present |
| `ide2` | WARN | Recovery/installer image should be present |

Each issue labeled `OK`, `WARN`, or `FAIL` with a fix command where applicable.

**Exit codes:** `0` all passed, `1` warnings only, `2` invalid VMID, `4` failures detected.

**Example:**
```bash
osx-next-cli doctor --vmid 100
```

Sample output (all passing):
```
  [ OK  ] balloon=0 — macOS has no balloon driver
  [ OK  ] machine=pc-q35-8.1+pve0
  [ OK  ] cores=4 — power-of-2, safe for macOS
  [ OK  ] memory=4096 MB
  [ OK  ] cpu=host
  [ OK  ] net0 model=vmxnet3 — native macOS driver
  [ OK  ] agent=enabled — graceful shutdown works
  [ OK  ] smbios1 set — identity chain configured
  [ OK  ] boot=order=ide2;virtio0;ide0
  [ OK  ] virtio0 present — main macOS disk
  [ OK  ] ide0 present — OpenCore bootloader
  [ OK  ] ide2 present — recovery/installer image

  All checks passed.
```

Sample output (with failures):
```
  [FAIL] balloon=1 — macOS will crash with balloon driver enabled
          Fix: qm set 100 --balloon 0
  [ WARN] cores=3 — non-power-of-2 value hangs macOS at Apple logo
          Fix: qm set 100 --cores 2
  ...

  1 failure, 1 warning
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Warnings (`doctor` with warnings but no failures), or `install-unattended` timed out |
| 2 | Validation error (bad VMID, invalid config, VM not found) |
| 3 | Missing assets (OpenCore or recovery image not found) |
| 4 | Execution failure (`apply`, or `doctor` with failures) |
| 5 | Download failed |
| 6 | Destroy failed |
| 7 | Edit failed |
| 8 | Clone failed |
| 9 | Post-install failed |
