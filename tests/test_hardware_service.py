"""Tests for host device discovery (services/hardware_service.py)."""
from __future__ import annotations

import json

from osx_proxmox_next.infrastructure import CommandResult
from osx_proxmox_next.services import hardware_service as hw


# ── Helpers ──────────────────────────────────────────────────────────


def _ok(output: str) -> CommandResult:
    return CommandResult(ok=True, returncode=0, output=output)


def _fail(output: str = "not found") -> CommandResult:
    return CommandResult(ok=False, returncode=127, output=output)


class FakePve:
    """Adapter stub that answers by command prefix."""

    def __init__(self, table: dict[str, CommandResult]):
        self.table = table
        self.calls: list[str] = []

    def run(self, argv):
        key = " ".join(argv)
        self.calls.append(key)
        for prefix, result in self.table.items():
            if key.startswith(prefix):
                return result
        return _fail(f"no such command: {key}")

    def qm(self, *args):
        return self.run(["qm", *args])

    def pvesm(self, *args):
        return self.run(["pvesm", *args])

    def pvesh(self, *args):
        return self.run(["pvesh", *args])


PCI_JSON = json.dumps([
    {"id": "0000:01:00.0", "vendor": "0x1002", "device": "0x73ff",
     "vendor_name": "Advanced Micro Devices, Inc. [AMD/ATI]",
     "device_name": "Navi 23 [Radeon RX 6600 XT]", "class": "0x030000", "iommugroup": 15},
    {"id": "0000:01:00.1", "vendor": "0x1002", "device": "0xab28",
     "vendor_name": "Advanced Micro Devices, Inc. [AMD/ATI]",
     "device_name": "Navi 21/23 HDMI/DP Audio", "class": "0x040300", "iommugroup": 15},
    {"id": "0000:03:00.0", "vendor": "0x10de", "device": "0x2484",
     "vendor_name": "NVIDIA Corporation", "device_name": "GA104 [GeForce RTX 3070]",
     "class": "0x030000", "iommugroup": 16},
    {"id": "0000:00:1f.3", "vendor": "0x8086", "device": "0xa348",
     "vendor_name": "Intel Corporation", "device_name": "Cannon Lake PCH cAVS",
     "class": "0x040300", "iommugroup": -1},
])

LSUSB = """Bus 002 Device 001: ID 1d6b:0003 Linux Foundation 3.0 root hub
Bus 001 Device 004: ID 058f:6387 Alcor Micro Corp. Flash Drive
Bus 001 Device 003: ID 046d:c52b Logitech, Inc. Unifying Receiver
Bus 001 Device 001: ID 1d6b:0002 Linux Foundation 2.0 root hub"""

LSPCI = (
    "0000:01:00.0 VGA compatible controller [0300]: Advanced Micro Devices, Inc. "
    "[AMD/ATI] Navi 23 [Radeon RX 6600 XT] [1002:73ff] (rev c7)\n"
    "0000:03:00.0 VGA compatible controller [0300]: NVIDIA Corporation "
    "GA104 [GeForce RTX 3070] [10de:2484] (rev a1)"
)


def _full_host() -> FakePve:
    return FakePve({
        "pvesh get /nodes --output-format json": _ok(json.dumps([{"node": "pve"}])),
        "hostname": _ok("pve\n"),
        "pvesh get /nodes/pve/hardware/pci": _ok(PCI_JSON),
        "lsusb": _ok(LSUSB),
    })


# ── Node name ────────────────────────────────────────────────────────


def test_node_name_from_api() -> None:
    assert hw.detect_node_name(_full_host()) == "pve"


def test_node_name_prefers_the_local_host_on_a_cluster() -> None:
    """Only local hardware can be passed through, so the local node wins."""
    pve = FakePve({
        "pvesh get /nodes --output-format json":
            _ok(json.dumps([{"node": "pve1"}, {"node": "pve2"}])),
        "hostname": _ok("pve2.example.com\n"),
    })
    assert hw.detect_node_name(pve) == "pve2"


def test_node_name_falls_back_to_hostname_without_pvesh() -> None:
    assert hw.detect_node_name(FakePve({"hostname": _ok("bare-metal\n")})) == "bare-metal"


def test_node_name_empty_when_nothing_answers() -> None:
    assert hw.detect_node_name(FakePve({})) == ""


def test_node_name_survives_non_json_from_pvesh() -> None:
    pve = FakePve({
        "pvesh get /nodes --output-format json": _ok("not json at all"),
        "hostname": _ok("pve\n"),
    })
    assert hw.detect_node_name(pve) == "pve"


# ── PCI ──────────────────────────────────────────────────────────────


def test_pci_devices_from_the_api() -> None:
    devices = hw.detect_pci_devices(_full_host())
    assert [d.slot for d in devices] == [
        "0000:01:00.0", "0000:01:00.1", "0000:03:00.0", "0000:00:1f.3"]
    gpu = devices[0]
    assert gpu.vendor_id == "1002" and gpu.device_id == "73ff"
    assert gpu.iommu_group == "15"
    assert "Radeon" in gpu.description


def test_pci_iommu_group_minus_one_reads_as_no_group() -> None:
    """-1 is the API's "not in a group", which is not a group you can pass."""
    devices = hw.detect_pci_devices(_full_host())
    assert devices[-1].iommu_group == ""


def test_pci_falls_back_to_lspci_when_the_api_is_gone() -> None:
    pve = FakePve({"hostname": _ok("pve\n"), "lspci -Dnn": _ok(LSPCI)})
    devices = hw.detect_pci_devices(pve)
    assert [d.slot for d in devices] == ["0000:01:00.0", "0000:03:00.0"]
    assert devices[0].vendor_id == "1002"
    assert devices[0].iommu_group == ""  # lspci does not report one


def test_pci_empty_when_neither_source_works() -> None:
    assert hw.detect_pci_devices(FakePve({})) == []


# ── GPU picker ───────────────────────────────────────────────────────


def test_gpu_picker_offers_amd_display_devices_only() -> None:
    """NVIDIA has no macOS driver, so offering one would offer a black screen."""
    gpus = hw.detect_gpu_devices(_full_host())
    assert len(gpus) == 1
    assert gpus[0].vendor_id == hw.AMD_VENDOR_ID
    assert "Radeon" in gpus[0].description


def test_gpu_picker_excludes_the_cards_own_audio_function() -> None:
    """01:00.1 is passed along with 01:00, so listing it would double it up."""
    gpus = hw.detect_gpu_devices(_full_host())
    assert [g.slot for g in gpus] == ["0000:01:00.0"]
    assert all("Audio" not in g.description for g in gpus)


def test_gpu_function_group_drops_the_function() -> None:
    """qm set -hostpci0 01:00 passes every function; 01:00.0 passes only video."""
    gpu = hw.detect_gpu_devices(_full_host())[0]
    assert gpu.function_group == "0000:01:00"


def test_gpu_label_shows_the_iommu_group() -> None:
    label = hw.detect_gpu_devices(_full_host())[0].label
    assert "0000:01:00" in label and "IOMMU 15" in label


def test_gpu_picker_deduplicates_functions_of_one_card() -> None:
    """Two display functions on one slot are one card, not two."""
    doubled = json.dumps([
        {"id": "0000:01:00.0", "vendor": "0x1002", "device": "0x73ff",
         "vendor_name": "AMD", "device_name": "Navi", "class": "0x030000"},
        {"id": "0000:01:00.2", "vendor": "0x1002", "device": "0x73fe",
         "vendor_name": "AMD", "device_name": "Navi second head", "class": "0x030000"},
    ])
    pve = FakePve({
        "pvesh get /nodes --output-format json": _ok(json.dumps([{"node": "pve"}])),
        "hostname": _ok("pve\n"),
        "pvesh get /nodes/pve/hardware/pci": _ok(doubled),
    })
    assert len(hw.detect_gpu_devices(pve)) == 1


# ── USB picker ───────────────────────────────────────────────────────


def test_usb_devices_parsed_from_lsusb() -> None:
    devices = hw.detect_usb_devices(_full_host())
    assert [d.device_id for d in devices] == ["058f:6387", "046d:c52b"]
    assert "Alcor" in devices[0].description
    assert devices[0].label.startswith("058f:6387")


def test_usb_drops_root_hubs() -> None:
    """Root hubs are not passable devices, only clutter."""
    ids = [d.device_id for d in hw.detect_usb_devices(_full_host())]
    assert "1d6b:0002" not in ids and "1d6b:0003" not in ids


def test_usb_deduplicates_identical_ids() -> None:
    """Two of the same model share one id, and qm can only address it once."""
    twins = ("Bus 001 Device 003: ID 058f:6387 Alcor Micro Corp. Flash Drive\n"
             "Bus 001 Device 004: ID 058f:6387 Alcor Micro Corp. Flash Drive")
    devices = hw.detect_usb_devices(FakePve({"lsusb": _ok(twins)}))
    assert len(devices) == 1


def test_usb_empty_without_lsusb() -> None:
    assert hw.detect_usb_devices(FakePve({})) == []


def test_usb_ignores_unparseable_lines() -> None:
    noisy = "Cannot open /dev/bus/usb\nBus 001 Device 004: ID 058f:6387 Flash Drive"
    devices = hw.detect_usb_devices(FakePve({"lsusb": _ok(noisy)}))
    assert [d.device_id for d in devices] == ["058f:6387"]
