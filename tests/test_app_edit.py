"""Tests for the Edit VM panel (EditModeMixin) in the manage tab."""
from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

from textual.widgets import Button, Checkbox, Input, Select, SelectionList, Static

from osx_proxmox_next import _edit_mixin as edit_mixin_module
from osx_proxmox_next.app import NextApp
from osx_proxmox_next.executor import ApplyResult
from osx_proxmox_next.rollback import RollbackSnapshot
from osx_proxmox_next.screens import CONSOLE_GPU_PRIMARY, VERBOSE_BOOT_KEEP
from osx_proxmox_next.services import edit_service
from osx_proxmox_next.services import VmInfo


# ── Helpers ──────────────────────────────────────────────────────────


async def _advance_to_manage(pilot, app) -> None:
    """Advance to step 2 and switch to Manage tab."""
    app.state.preflight_done = True
    app.state.preflight_ok = True
    app.query_one("#preflight_next_btn", Button).disabled = False
    await pilot.click("#preflight_next_btn")
    await pilot.pause()
    await pilot.click("#mode_manage")
    await pilot.pause()


# ── Edit VMID validation ──────────────────────────────────────────────


def test_edit_form_hidden_until_valid_vmid() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            # edit_form should start hidden
            assert app.query_one("#edit_form").has_class("hidden")
            # invalid vmid keeps form hidden
            app.query_one("#edit_vmid", Input).value = "abc"
            await pilot.pause()
            assert app.query_one("#edit_form").has_class("hidden")

    asyncio.run(_run())


def test_edit_form_shows_on_valid_vmid() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            assert not app.query_one("#edit_form").has_class("hidden")

    asyncio.run(_run())


def test_edit_apply_btn_disabled_without_any_field() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            # No fields filled → button disabled
            assert app.query_one("#edit_apply_btn", Button).disabled is True

    asyncio.run(_run())


def test_edit_apply_btn_enabled_with_one_field() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            app.query_one("#edit_cores", Input).value = "4"
            await pilot.pause()
            assert app.query_one("#edit_apply_btn", Button).disabled is False

    asyncio.run(_run())


def test_edit_vmid_out_of_range_keeps_form_hidden() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "5"
            await pilot.pause()
            assert app.query_one("#edit_form").has_class("hidden")

    asyncio.run(_run())


# ── Validation rejection via _run_edit ───────────────────────────────


def test_edit_run_edit_blocked_while_running() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.state.edit_running = True
            # should silently return without crashing
            app._run_edit()

    asyncio.run(_run())


def test_edit_run_edit_invalid_vmid_noop() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "abc"
            await pilot.pause()
            app._run_edit()  # should not raise

    asyncio.run(_run())


def test_edit_run_edit_shows_validation_errors() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            # bad cores value — validation should reject
            app.query_one("#edit_cores", Input).value = "1"  # below MIN_CORES
            await pilot.pause()
            app._run_edit()
            await pilot.pause()
            result_box = app.query_one("#edit_result", Static)
            assert not result_box.has_class("hidden")
            assert result_box.has_class("edit_result_fail")

    asyncio.run(_run())


# ── Start-after checkbox ──────────────────────────────────────────────


def test_edit_start_after_checkbox_updates_state() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            # Enter valid VMID so the edit form (and checkbox) become visible
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            assert app.state.edit_start_after is False
            await pilot.click("#edit_start_after_cb")
            await pilot.pause()
            assert app.state.edit_start_after is True
            await pilot.click("#edit_start_after_cb")
            await pilot.pause()
            assert app.state.edit_start_after is False

    asyncio.run(_run())


# ── Edit success / failure via monkeypatched edit_service ────────────


def test_edit_apply_success(monkeypatch) -> None:
    monkeypatch.setattr(
        edit_mixin_module, "fetch_vm_info",
        lambda vmid, adapter=None: VmInfo(vmid=vmid, name="test-vm", status="running", config_raw=""),
    )
    monkeypatch.setattr(
        edit_mixin_module, "create_snapshot",
        lambda vmid: RollbackSnapshot(vmid=vmid, path=Path("/tmp/snap.conf")),
    )

    def fake_apply_plan(steps, execute=False, on_step=None, adapter=None):
        for idx, step in enumerate(steps, start=1):
            if on_step:
                on_step(idx, len(steps), step, None)

                class _R:
                    ok = True
                    returncode = 0

                on_step(idx, len(steps), step, _R())
        return ApplyResult(ok=True, results=[], log_path=Path("/tmp/edit.log"))

    monkeypatch.setattr(edit_service, "apply_plan", fake_apply_plan)

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            app.query_one("#edit_cores", Input).value = "4"
            await pilot.pause()
            await pilot.click("#edit_apply_btn")
            for _ in range(30):
                await pilot.pause()
                time.sleep(0.05)
                if app.state.edit_done:
                    break
            assert app.state.edit_ok is True
            result_text = str(app.query_one("#edit_result", Static).content)
            assert "Changes applied" in result_text

    asyncio.run(_run())


def test_edit_apply_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        edit_mixin_module, "fetch_vm_info",
        lambda vmid, adapter=None: VmInfo(vmid=vmid, name="test-vm", status="running", config_raw=""),
    )
    monkeypatch.setattr(
        edit_mixin_module, "create_snapshot",
        lambda vmid: RollbackSnapshot(vmid=vmid, path=Path("/tmp/snap.conf")),
    )
    monkeypatch.setattr(
        edit_service,
        "apply_plan",
        lambda steps, execute=False, on_step=None, adapter=None: ApplyResult(
            ok=False, results=[], log_path=Path("/tmp/fail.log")
        ),
    )

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            app.query_one("#edit_memory", Input).value = "8192"
            await pilot.pause()
            await pilot.click("#edit_apply_btn")
            for _ in range(30):
                await pilot.pause()
                time.sleep(0.05)
                if app.state.edit_done:
                    break
            assert app.state.edit_ok is False
            result_text = str(app.query_one("#edit_result", Static).content)
            assert "Failed" in result_text

    asyncio.run(_run())


# ── _update_edit_log ─────────────────────────────────────────────────


def test_edit_update_log_before_result() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_log").remove_class("hidden")
            app._update_edit_log(1, 2, "Stop VM", None)
            log_text = str(app.query_one("#edit_log", Static).content)
            assert "Running 1/2: Stop VM" in log_text

    asyncio.run(_run())


def test_edit_update_log_with_ok_result() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_log").remove_class("hidden")

            class _R:
                ok = True

            app._update_edit_log(1, 1, "Set cores", _R())
            log_text = str(app.query_one("#edit_log", Static).content)
            assert "OK 1/1: Set cores" in log_text

    asyncio.run(_run())


# ── _finish_edit ─────────────────────────────────────────────────────


def test_edit_finish_edit_success_clears_running() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.state.edit_running = True
            app._finish_edit(ok=True, log_path=Path("/tmp/ok.log"))
            await pilot.pause()
            assert app.state.edit_running is False
            assert app.state.edit_ok is True
            result_box = app.query_one("#edit_result", Static)
            assert not result_box.has_class("hidden")
            assert not result_box.has_class("edit_result_fail")

    asyncio.run(_run())


def test_edit_finish_edit_failure_marks_fail() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.state.edit_running = True
            app._finish_edit(ok=False, log_path=Path("/tmp/fail.log"))
            await pilot.pause()
            assert app.state.edit_ok is False
            result_box = app.query_one("#edit_result", Static)
            assert result_box.has_class("edit_result_fail")

    asyncio.run(_run())


# ── VM not found ────────────────────────────────────────────────────


def test_edit_apply_vm_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        edit_mixin_module, "fetch_vm_info",
        lambda vmid, adapter=None: None,
    )

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            app.query_one("#edit_cores", Input).value = "4"
            await pilot.pause()
            await pilot.click("#edit_apply_btn")
            for _ in range(30):
                await pilot.pause()
                time.sleep(0.05)
                if app.state.edit_done:
                    break
            assert app.state.edit_ok is False
            result_box = app.query_one("#edit_result", Static)
            assert result_box.has_class("edit_result_fail")

    asyncio.run(_run())


# ── WizardState edit defaults ────────────────────────────────────────


def test_wizard_state_edit_defaults() -> None:
    from osx_proxmox_next.models import WizardState
    state = WizardState()
    assert state.edit_running is False
    assert state.edit_done is False
    assert state.edit_ok is False
    assert state.edit_log == []
    assert state.edit_start_after is False


# ── Verbose boot on an existing VM ───────────────────────────────────


def test_edit_verbose_boot_defaults_to_keeping_the_current_setting() -> None:
    """Opening the panel must not arm a boot-args rewrite."""
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            assert app.query_one("#edit_verbose_boot", Select).value == VERBOSE_BOOT_KEEP
            assert app._read_edit_verbose_boot() is None
            # "Keep" alone is not a change, so Apply stays disabled.
            assert app.query_one("#edit_apply_btn", Button).disabled is True

    asyncio.run(_run())


def test_edit_verbose_boot_selection_maps_to_the_tri_state() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            select = app.query_one("#edit_verbose_boot", Select)
            for value, expected in (("on", True), ("off", False), (VERBOSE_BOOT_KEEP, None)):
                select.value = value
                await pilot.pause()
                assert app._read_edit_verbose_boot() is expected, value

    asyncio.run(_run())


def test_edit_verbose_boot_alone_enables_apply() -> None:
    """Every other field is blank, but picking On is still a real change."""
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            app.query_one("#edit_verbose_boot", Select).value = "off"
            await pilot.pause()
            assert app.query_one("#edit_apply_btn", Button).disabled is False

    asyncio.run(_run())


def test_edit_verbose_boot_reaches_the_edit_plan(monkeypatch) -> None:
    """The select is what puts the boot-args step into the plan."""
    captured: list = []

    monkeypatch.setattr(
        edit_mixin_module, "fetch_vm_info",
        lambda vmid, adapter=None: VmInfo(vmid=vmid, name="test-vm", status="running", config_raw=""),
    )
    monkeypatch.setattr(
        edit_mixin_module, "create_snapshot",
        lambda vmid: RollbackSnapshot(vmid=vmid, path=Path("/tmp/snap.conf")),
    )

    def fake_apply_plan(steps, execute=False, on_step=None, adapter=None):
        captured.extend(steps)
        return ApplyResult(ok=True, results=[], log_path=Path("/tmp/edit.log"))

    monkeypatch.setattr(edit_service, "apply_plan", fake_apply_plan)

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            app.query_one("#edit_verbose_boot", Select).value = "on"
            await pilot.pause()
            await pilot.click("#edit_apply_btn")
            for _ in range(30):
                await pilot.pause()
                time.sleep(0.05)
                if app.state.edit_done:
                    break
            assert app.state.edit_ok is True
            titles = [s.title for s in captured]
            assert "Turn verbose boot on (OpenCore boot-args)" in titles
            # A successful apply resets the select, so a second Apply is not a
            # silent re-run of the same boot-args rewrite.
            assert app.query_one("#edit_verbose_boot", Select).value == VERBOSE_BOOT_KEEP
            assert app.query_one("#edit_apply_btn", Button).disabled is True

    asyncio.run(_run())


def test_edit_other_fields_leave_boot_args_alone(monkeypatch) -> None:
    """Changing only the core count must not mount and rewrite the OC disk."""
    captured: list = []

    monkeypatch.setattr(
        edit_mixin_module, "fetch_vm_info",
        lambda vmid, adapter=None: VmInfo(vmid=vmid, name="test-vm", status="running", config_raw=""),
    )
    monkeypatch.setattr(
        edit_mixin_module, "create_snapshot",
        lambda vmid: RollbackSnapshot(vmid=vmid, path=Path("/tmp/snap.conf")),
    )

    def fake_apply_plan(steps, execute=False, on_step=None, adapter=None):
        captured.extend(steps)
        return ApplyResult(ok=True, results=[], log_path=Path("/tmp/edit.log"))

    monkeypatch.setattr(edit_service, "apply_plan", fake_apply_plan)

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            app.query_one("#edit_cores", Input).value = "4"
            await pilot.pause()
            await pilot.click("#edit_apply_btn")
            for _ in range(30):
                await pilot.pause()
                time.sleep(0.05)
                if app.state.edit_done:
                    break
            assert not any("verbose boot" in s.title for s in captured)

    asyncio.run(_run())


# ── GPU / USB passthrough in the Edit VM panel ───────────────────────


def _fake_devices(monkeypatch, gpus=None, usb=None) -> None:
    """Stand in for the host hardware scan."""
    from osx_proxmox_next.services import PciDevice, UsbDevice
    if gpus is None:
        gpus = [PciDevice(slot="0000:01:00.0", vendor_id="1002", device_id="73ff",
                          description="Radeon RX 6600 XT", class_id="0x030000",
                          iommu_group="15")]
    if usb is None:
        usb = [UsbDevice(device_id="058f:6387", description="Alcor Flash Drive"),
               UsbDevice(device_id="046d:c52b", description="Logitech Receiver")]
    monkeypatch.setattr(edit_mixin_module, "detect_gpu_devices", lambda adapter=None: gpus)
    monkeypatch.setattr(edit_mixin_module, "detect_usb_devices", lambda adapter=None: usb)


def _fake_vm_config(monkeypatch, config: str) -> None:
    monkeypatch.setattr(
        edit_mixin_module, "fetch_vm_info",
        lambda vmid, adapter=None: VmInfo(vmid=vmid, name="test-vm",
                                          status="stopped", config_raw=config),
    )


async def _open_edit(pilot, app, vmid: str = "900") -> None:
    await _advance_to_manage(pilot, app)
    app.query_one("#edit_vmid", Input).value = vmid
    for _ in range(20):
        await pilot.pause()
        time.sleep(0.02)
        if app.state.edit_devices_loaded and app.state.edit_usb_known:
            break


def test_edit_gpu_dropdown_lists_detected_cards(monkeypatch) -> None:
    _fake_devices(monkeypatch)
    _fake_vm_config(monkeypatch, "name: test-vm\n")

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _open_edit(pilot, app)
            assert app.state.edit_host_gpus
            # Blank is "keep unchanged", so a finished scan arms nothing.
            assert not isinstance(app.query_one("#edit_gpu", Select).value, str)
            assert app._read_edit_gpu() is None

    asyncio.run(_run())


def test_edit_gpu_selection_becomes_the_attach_address(monkeypatch) -> None:
    _fake_devices(monkeypatch)
    _fake_vm_config(monkeypatch, "name: test-vm\n")

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _open_edit(pilot, app)
            app.query_one("#edit_gpu", Select).value = "0000:01:00"
            await pilot.pause()
            assert app._read_edit_gpu() == "0000:01:00"
            assert app.query_one("#edit_apply_btn", Button).disabled is False

    asyncio.run(_run())


def test_edit_gpu_typed_address_wins_over_the_dropdown(monkeypatch) -> None:
    """The free-text field exists for the card the scan did not offer."""
    _fake_devices(monkeypatch)
    _fake_vm_config(monkeypatch, "name: test-vm\n")

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _open_edit(pilot, app)
            app.query_one("#edit_gpu", Select).value = "0000:01:00"
            app.query_one("#edit_gpu_address", Input).value = "03:00"
            await pilot.pause()
            assert app._read_edit_gpu() == "03:00"

    asyncio.run(_run())


def test_edit_console_selector_drives_gpu_primary(monkeypatch) -> None:
    _fake_devices(monkeypatch)
    _fake_vm_config(monkeypatch, "name: test-vm\n")

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _open_edit(pilot, app)
            assert app._read_edit_console_primary() is False
            app.query_one("#edit_console", Select).value = CONSOLE_GPU_PRIMARY
            await pilot.pause()
            assert app._read_edit_console_primary() is True

    asyncio.run(_run())


def test_edit_usb_list_starts_matching_the_vm(monkeypatch) -> None:
    """Ticks mirror the VM, so unticking is what asks for a detach."""
    _fake_devices(monkeypatch)
    _fake_vm_config(monkeypatch, "name: test-vm\nusb0: host=058f:6387\n")

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _open_edit(pilot, app)
            assert app.state.edit_current_usb == ["058f:6387"]
            assert set(app.query_one("#edit_usb_list", SelectionList).selected) == {"058f:6387"}
            # Matching the VM is not a change, so Apply stays disabled.
            assert app._edit_usb_changed() is False
            assert app.query_one("#edit_apply_btn", Button).disabled is True

    asyncio.run(_run())


def test_edit_usb_unticking_asks_for_a_detach(monkeypatch) -> None:
    _fake_devices(monkeypatch)
    _fake_vm_config(monkeypatch, "name: test-vm\nusb0: host=058f:6387\n")

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _open_edit(pilot, app)
            app.query_one("#edit_usb_list", SelectionList).deselect_all()
            await pilot.pause()
            assert app._read_edit_usb() == []
            assert app._edit_usb_changed() is True
            assert app.query_one("#edit_apply_btn", Button).disabled is False

    asyncio.run(_run())


def test_edit_usb_list_keeps_a_row_for_an_unplugged_device(monkeypatch) -> None:
    """A device the VM holds but the host no longer sees must stay untickable."""
    _fake_devices(monkeypatch)
    _fake_vm_config(monkeypatch, "name: test-vm\nusb0: host=dead:beef\n")

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _open_edit(pilot, app)
            widget = app.query_one("#edit_usb_list", SelectionList)
            assert "dead:beef" in set(widget.selected)

    asyncio.run(_run())


def test_edit_usb_left_alone_until_the_config_is_read(monkeypatch) -> None:
    """An empty list before load means not-known-yet, never detach-everything."""
    _fake_devices(monkeypatch)
    monkeypatch.setattr(edit_mixin_module, "fetch_vm_info",
                        lambda vmid, adapter=None: None)

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            for _ in range(15):
                await pilot.pause()
                time.sleep(0.02)
            assert app.state.edit_usb_known is False
            assert app._read_edit_usb() is None
            assert app._edit_usb_changed() is False

    asyncio.run(_run())


def test_edit_usb_manual_ids_join_the_selection(monkeypatch) -> None:
    _fake_devices(monkeypatch)
    _fake_vm_config(monkeypatch, "name: test-vm\n")

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _open_edit(pilot, app)
            app.query_one("#edit_usb_manual", Input).value = "05AC:12A8, 2-1.2.2"
            await pilot.pause()
            assert app._read_edit_usb() == ["05ac:12a8", "2-1.2.2"]

    asyncio.run(_run())


def test_edit_passthrough_reaches_the_plan(monkeypatch) -> None:
    captured: list = []
    _fake_devices(monkeypatch)
    _fake_vm_config(monkeypatch, "name: test-vm\nusb0: host=058f:6387\n")
    monkeypatch.setattr(
        edit_mixin_module, "create_snapshot",
        lambda vmid: RollbackSnapshot(vmid=vmid, path=Path("/tmp/snap.conf")),
    )

    def fake_apply_plan(steps, execute=False, on_step=None, adapter=None):
        captured.extend(steps)
        return ApplyResult(ok=True, results=[], log_path=Path("/tmp/edit.log"))

    monkeypatch.setattr(edit_service, "apply_plan", fake_apply_plan)

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _open_edit(pilot, app)
            app.query_one("#edit_gpu", Select).value = "0000:01:00"
            app.query_one("#edit_console", Select).value = CONSOLE_GPU_PRIMARY
            app.query_one("#edit_usb_list", SelectionList).deselect_all()
            await pilot.pause()
            await pilot.click("#edit_apply_btn")
            for _ in range(30):
                await pilot.pause()
                time.sleep(0.05)
                if app.state.edit_done:
                    break
            titles = [s.title for s in captured]
            assert "Attach GPU 0000:01:00 (hostpci0,pcie=1,x-vga=1)" in titles
            assert "Disable Proxmox console (GPU is primary)" in titles
            assert "Detach USB device 058f:6387 (usb0)" in titles

    asyncio.run(_run())


def test_edit_success_resets_the_passthrough_controls(monkeypatch) -> None:
    _fake_devices(monkeypatch)
    _fake_vm_config(monkeypatch, "name: test-vm\n")
    monkeypatch.setattr(
        edit_mixin_module, "create_snapshot",
        lambda vmid: RollbackSnapshot(vmid=vmid, path=Path("/tmp/snap.conf")),
    )
    monkeypatch.setattr(
        edit_service, "apply_plan",
        lambda steps, execute=False, on_step=None, adapter=None:
            ApplyResult(ok=True, results=[], log_path=Path("/tmp/edit.log")),
    )

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _open_edit(pilot, app)
            app.query_one("#edit_gpu", Select).value = "0000:01:00"
            app.query_one("#edit_gpu_address", Input).value = "03:00"
            await pilot.pause()
            await pilot.click("#edit_apply_btn")
            for _ in range(30):
                await pilot.pause()
                time.sleep(0.05)
                if app.state.edit_done:
                    break
            assert app._read_edit_gpu() is None
            assert app.query_one("#edit_gpu_address", Input).value == ""
            assert app.query_one("#edit_usb_manual", Input).value == ""

    asyncio.run(_run())


# ── Panel scrolling ──────────────────────────────────────────────────
#
# Textual's Vertical/Container default to `height: 1fr; overflow: hidden`, so a
# panel that outgrows the viewport clips its own tail rather than growing. #body
# can only scroll content taller than itself, so a clipped panel makes the
# fields below the fold unreachable with no scrollbar to say so.


def _short_terminal() -> tuple[int, int]:
    """A terminal too short for the Edit VM form, which is the whole point."""
    return (100, 24)


def test_stacking_panels_size_to_their_content() -> None:
    """These three clipped their overflow instead of growing #body."""
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=_short_terminal()) as pilot:
            await pilot.pause()
            for selector in ("#create_panel", "#edit_form", "#apple_services_fields"):
                height = app.query_one(selector).styles.height
                assert height is not None and height.is_auto, selector

    asyncio.run(_run())


def test_body_is_the_scrolling_surface() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=_short_terminal()) as pilot:
            await pilot.pause()
            body = app.query_one("#body")
            assert body.styles.overflow_y == "auto"
            assert body.allow_vertical_scroll

    asyncio.run(_run())


def test_edit_vm_form_can_be_scrolled_to_the_bottom() -> None:
    """The reported bug: the fields below the fold could not be reached."""
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=_short_terminal()) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            body = app.query_one("#body")
            # The open form is taller than this terminal, so there is something
            # to scroll -- before the fix the panel was clipped to the viewport
            # and max_scroll_y stayed 0.
            assert body.max_scroll_y > 0

            body.scroll_end(animate=False)
            await pilot.pause()
            assert body.scroll_offset.y > 0

    asyncio.run(_run())


def test_page_down_binding_scrolls_the_body() -> None:
    """Mouse reporting is often off over SSH, so the keyboard has to work."""
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=_short_terminal()) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            body = app.query_one("#body")
            assert body.scroll_offset.y == 0

            app.action_page_body_down()
            await pilot.pause()
            scrolled = body.scroll_offset.y
            assert scrolled > 0

            app.action_page_body_up()
            await pilot.pause()
            assert body.scroll_offset.y < scrolled

    asyncio.run(_run())


def test_apply_button_is_reachable_once_scrolled() -> None:
    """Scrolling is only a fix if the control at the bottom becomes usable."""
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=_short_terminal()) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            app.query_one("#edit_vmid", Input).value = "900"
            await pilot.pause()
            button = app.query_one("#edit_apply_btn", Button)
            app.query_one("#body").scroll_to_widget(button, animate=False)
            await pilot.pause()
            assert button.region.height > 0  # actually laid out, not clipped away

    asyncio.run(_run())


# ── Leaving the Manage panel ─────────────────────────────────────────
#
# The wizard's Exit buttons all sit in the Create panel, which is hidden while
# managing, so once an edit had been applied the only way out was the q/escape
# binding - not something the panel says anywhere.


def test_manage_panel_has_its_own_exit_button() -> None:
    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _advance_to_manage(pilot, app)
            button = app.query_one("#exit_btn_manage", Button)
            assert not button.disabled
            assert not app.query_one("#manage_panel").has_class("hidden")

    asyncio.run(_run())


def test_manage_exit_button_closes_the_app(monkeypatch) -> None:
    _fake_devices(monkeypatch)
    _fake_vm_config(monkeypatch, "name: test-vm\n")
    monkeypatch.setattr(
        edit_mixin_module, "create_snapshot",
        lambda vmid: RollbackSnapshot(vmid=vmid, path=Path("/tmp/snap.conf")),
    )
    monkeypatch.setattr(
        edit_service, "apply_plan",
        lambda steps, execute=False, on_step=None, adapter=None:
            ApplyResult(ok=True, results=[], log_path=Path("/tmp/edit.log")),
    )

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _open_edit(pilot, app)
            app.query_one("#edit_cores", Input).value = "4"
            await pilot.pause()
            await pilot.click("#edit_apply_btn")
            for _ in range(30):
                await pilot.pause()
                time.sleep(0.05)
                if app.state.edit_done:
                    break
            assert app.state.edit_ok
            # The result says where to go next, and that button is live again.
            assert "Exit" in str(app.query_one("#edit_result", Static).renderable)
            button = app.query_one("#exit_btn_manage", Button)
            assert not button.disabled

            # Stand in for App.exit rather than really tearing the app down:
            # the run_test harness owns the shutdown, and what is under test is
            # that this button reaches the exit path at all.
            exits: list[bool] = []
            app.exit = lambda *a, **kw: exits.append(True)  # type: ignore[method-assign]
            try:
                app.on_button_pressed(Button.Pressed(button))
            finally:
                del app.exit  # type: ignore[attr-defined]
            assert exits == [True]

    asyncio.run(_run())


def test_manage_exit_is_disabled_while_an_edit_runs(monkeypatch) -> None:
    """Exiting mid-apply would tear the app down over a half-written VM."""
    _fake_devices(monkeypatch)
    _fake_vm_config(monkeypatch, "name: test-vm\n")
    monkeypatch.setattr(
        edit_mixin_module, "create_snapshot",
        lambda vmid: RollbackSnapshot(vmid=vmid, path=Path("/tmp/snap.conf")),
    )
    release = threading.Event()

    def slow_apply_plan(steps, execute=False, on_step=None, adapter=None):
        release.wait(5)  # held open so the test can look at the panel mid-apply
        return ApplyResult(ok=True, results=[], log_path=Path("/tmp/edit.log"))

    monkeypatch.setattr(edit_service, "apply_plan", slow_apply_plan)

    async def _run() -> None:
        app = NextApp()
        async with app.run_test(size=(120, 80)) as pilot:
            await pilot.pause()
            await _open_edit(pilot, app)
            app.query_one("#edit_cores", Input).value = "4"
            await pilot.pause()
            await pilot.click("#edit_apply_btn")
            for _ in range(30):
                await pilot.pause()
                time.sleep(0.02)
                if app.state.edit_running:
                    break
            try:
                assert app.query_one("#exit_btn_manage", Button).disabled
            finally:
                release.set()
            for _ in range(30):
                await pilot.pause()
                time.sleep(0.05)
                if app.state.edit_done:
                    break
            assert not app.query_one("#exit_btn_manage", Button).disabled

    asyncio.run(_run())
