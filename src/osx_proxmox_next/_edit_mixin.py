from __future__ import annotations

import logging
import tempfile
import traceback
from pathlib import Path
from threading import Thread

from textual.widgets import Button, Checkbox, Input, Select, SelectionList, Static

from .domain import (
    MAX_VMID,
    MIN_VMID,
    GPU_HOSTPCI_INDEX,
    EditChanges,
    PlanStep,
    validate_edit_changes,
)
from .executor import StepResult
from .rollback import create_snapshot
from .planner import _parse_indexed_entries, _usb_host_id
from .screens import (
    CONSOLE_GPU_PRIMARY,
    VERBOSE_BOOT_KEEP,
    gpu_choices,
    gpu_hint_text,
    usb_hint_text,
)
from .services import (
    detect_gpu_devices,
    detect_usb_devices,
    fetch_vm_info,
    get_proxmox_adapter,
    run_edit_worker,
)

log = logging.getLogger(__name__)

__all__ = ["EditModeMixin"]


class EditModeMixin:
    """Mixin providing the Edit VM panel methods for NextApp."""

    # ── Host device discovery ────────────────────────────────────────

    def _refresh_host_devices(self) -> None:
        """Scan the host for passable devices, once per visit to Manage."""
        if self.state.edit_devices_loaded:  # type: ignore[attr-defined]
            return
        Thread(target=self._host_devices_worker, daemon=True).start()

    def _host_devices_worker(self) -> None:
        try:
            adapter = get_proxmox_adapter()
            gpus = detect_gpu_devices(adapter)
            usb = detect_usb_devices(adapter)
        except (OSError, RuntimeError):
            log.debug("Host device scan failed", exc_info=True)
            gpus, usb = [], []
        self.call_from_thread(self._finish_host_devices, gpus, usb)  # type: ignore[attr-defined]

    def _finish_host_devices(self, gpus: list, usb: list) -> None:
        self.state.edit_host_gpus = gpus  # type: ignore[attr-defined]
        self.state.edit_host_usb = usb  # type: ignore[attr-defined]
        self.state.edit_devices_loaded = True  # type: ignore[attr-defined]
        # set_options resets the select to blank, which is "keep unchanged":
        # a finished host scan must not arm a GPU change on its own.
        self.query_one("#edit_gpu", Select).set_options(gpu_choices(gpus))
        self._render_usb_list()
        self._update_passthrough_hints()

    def _refresh_edit_vm_devices(self, vmid: int) -> None:
        """Load which devices *vmid* already has, so the USB list can start true.

        Without this the tick boxes would be a blank slate and unticking could
        not mean "detach": the panel has to know what is attached before it can
        offer to take it away.
        """
        if self.state.edit_loaded_vmid == vmid:  # type: ignore[attr-defined]
            return
        self.state.edit_loaded_vmid = vmid  # type: ignore[attr-defined]
        Thread(target=self._edit_vm_devices_worker, args=(vmid,), daemon=True).start()

    def _edit_vm_devices_worker(self, vmid: int) -> None:
        try:
            info = fetch_vm_info(vmid, adapter=get_proxmox_adapter())
            config = info.config_raw if info else ""
        except (OSError, RuntimeError):
            log.debug("Could not read config for VM %s", vmid, exc_info=True)
            config = ""
        self.call_from_thread(self._finish_edit_vm_devices, vmid, config)  # type: ignore[attr-defined]

    def _finish_edit_vm_devices(self, vmid: int, config: str) -> None:
        # A slower scan for a VMID the user has since typed past must not
        # overwrite the state of the one now in the box.
        if self.state.edit_loaded_vmid != vmid:  # type: ignore[attr-defined]
            return
        hostpci = _parse_indexed_entries(config, "hostpci")
        usb = _parse_indexed_entries(config, "usb")
        self.state.edit_current_gpu = hostpci.get(GPU_HOSTPCI_INDEX, "")  # type: ignore[attr-defined]
        self.state.edit_current_usb = [  # type: ignore[attr-defined]
            host_id for host_id in (_usb_host_id(entry) for entry in usb.values()) if host_id
        ]
        # Only now is unticking safe to read as "detach": before the config
        # arrives an empty list means "not known yet", not "detach everything".
        self.state.edit_usb_known = bool(config)  # type: ignore[attr-defined]
        self._render_usb_list()
        self._update_passthrough_hints()
        self._validate_edit_form()

    def _render_usb_list(self) -> None:
        """Rebuild the USB tick list: host devices, pre-ticked to match the VM."""
        widget = self.query_one("#edit_usb_list", SelectionList)
        attached = list(self.state.edit_current_usb)  # type: ignore[attr-defined]
        options = [
            (device.label, device.device_id, device.device_id in attached)
            for device in self.state.edit_host_usb  # type: ignore[attr-defined]
        ]
        listed = {device.device_id for device in self.state.edit_host_usb}  # type: ignore[attr-defined]
        # A device the VM holds but the host no longer reports is still worth a
        # row - otherwise it could never be unticked and so never detached.
        options.extend(
            (f"{host_id}  (attached, not connected to this host)", host_id, True)
            for host_id in attached if host_id not in listed
        )
        widget.clear_options()
        if options:
            widget.add_options(options)

    def _update_passthrough_hints(self) -> None:
        self.query_one("#edit_gpu_hint", Static).update(
            gpu_hint_text(
                len(self.state.edit_host_gpus),  # type: ignore[attr-defined]
                self.state.edit_current_gpu,  # type: ignore[attr-defined]
            )
        )
        self.query_one("#edit_usb_hint", Static).update(
            usb_hint_text(len(self.state.edit_host_usb))  # type: ignore[attr-defined]
        )

    # ── Reading the passthrough controls ─────────────────────────────

    def _read_edit_gpu(self) -> str | None:
        """Return the GPU address to attach, DETACH_DEVICE, or None to keep.

        A typed address wins over the dropdown: it is there precisely for the
        card the host scan did not offer.
        """
        typed = self.query_one("#edit_gpu_address", Input).value.strip()
        if typed:
            return typed
        value = self.query_one("#edit_gpu", Select).value
        # Select.BLANK is the "Keep unchanged" prompt, and is not a string.
        return value if isinstance(value, str) else None

    def _read_edit_console_primary(self) -> bool:
        return self.query_one("#edit_console", Select).value == CONSOLE_GPU_PRIMARY

    def _read_edit_usb(self) -> list[str] | None:
        """Return the USB devices the VM should end up with, or None to keep.

        Returns None until the VM's own config has been read. This is a set,
        not a list of additions, so acting on it without knowing what the VM
        already has would detach every device the panel could not see -- and
        the config being unreadable is the worst moment to guess.
        """
        if not self.state.edit_usb_known:  # type: ignore[attr-defined]
            return None
        manual = [
            part.strip().lower()
            for part in self.query_one("#edit_usb_manual", Input).value.split(",")
            if part.strip()
        ]
        selected = [str(value) for value in self.query_one("#edit_usb_list", SelectionList).selected]
        for device in manual:
            if device not in selected:
                selected.append(device)
        return selected

    def _edit_usb_changed(self) -> bool:
        """True when the requested USB set differs from what the VM has."""
        wanted = self._read_edit_usb()
        if wanted is None:
            return False
        return set(wanted) != set(self.state.edit_current_usb)  # type: ignore[attr-defined]

    def _validate_edit_form(self) -> None:
        try:
            vmid = int(self.query_one("#edit_vmid", Input).value.strip())
            valid_vmid = MIN_VMID <= vmid <= MAX_VMID
        except ValueError:
            valid_vmid = False

        form = self.query_one("#edit_form")
        if valid_vmid:
            form.remove_class("hidden")
            # Reading the VM's own devices is what lets the USB list start out
            # matching it; it is a no-op once this VMID has been read.
            self._refresh_edit_vm_devices(vmid)
        else:
            form.add_class("hidden")
            self.query_one("#edit_apply_btn", Button).disabled = True
            return

        has_any = any(
            self.query_one(sel, Input).value.strip()
            for sel in ("#edit_name", "#edit_cores", "#edit_memory", "#edit_bridge", "#edit_disk_add")
        ) or self._read_edit_verbose_boot() is not None \
            or self._read_edit_gpu() is not None \
            or self._edit_usb_changed()
        self.query_one("#edit_apply_btn", Button).disabled = not has_any

    def _read_edit_verbose_boot(self) -> bool | None:
        """Return the requested verbose-boot state, or None to leave it alone."""
        value = self.query_one("#edit_verbose_boot", Select).value
        if value == VERBOSE_BOOT_KEEP:
            return None
        return value == "on"

    def _run_edit(self) -> None:
        if self.state.edit_running:  # type: ignore[attr-defined]
            return
        try:
            vmid = int(self.query_one("#edit_vmid", Input).value.strip())
        except ValueError:
            return
        if vmid < MIN_VMID or vmid > MAX_VMID:
            return

        def _opt_int(sel: str) -> int | None:
            v = self.query_one(sel, Input).value.strip()
            if not v:
                return None
            try:
                return int(v)
            except ValueError:
                return None

        def _opt_str(sel: str) -> str | None:
            v = self.query_one(sel, Input).value.strip()
            return v if v else None

        changes = EditChanges(
            name=_opt_str("#edit_name"),
            cores=_opt_int("#edit_cores"),
            memory_mb=_opt_int("#edit_memory"),
            bridge=_opt_str("#edit_bridge"),
            disk_gb_add=_opt_int("#edit_disk_add"),
            nic_model=_opt_str("#edit_nic_model"),
            disk_name=_opt_str("#edit_disk_name") or "virtio0",
            verbose_boot=self._read_edit_verbose_boot(),
            gpu_device=self._read_edit_gpu(),
            gpu_primary=self._read_edit_console_primary(),
            usb_devices=self._read_edit_usb() if self._edit_usb_changed() else None,
        )

        issues = validate_edit_changes(vmid, changes)
        if issues:
            result_box = self.query_one("#edit_result", Static)
            result_box.remove_class("hidden")
            result_box.add_class("edit_result_fail")
            result_box.update("\n".join(issues))
            return

        start_after = self.state.edit_start_after  # type: ignore[attr-defined]

        self.state.edit_running = True  # type: ignore[attr-defined]
        self.state.edit_done = False  # type: ignore[attr-defined]
        self.state.edit_log = []  # type: ignore[attr-defined]
        self.query_one("#edit_apply_btn", Button).disabled = True
        self.query_one("#edit_log").remove_class("hidden")
        self.query_one("#edit_log", Static).update("Applying changes...")
        self.query_one("#edit_result").add_class("hidden")

        Thread(target=self._edit_worker, args=(vmid, changes, start_after), daemon=True).start()

    def _edit_worker(self, vmid: int, changes: EditChanges, start_after: bool) -> None:
        def on_step(idx: int, total: int, step: PlanStep, result: StepResult | None) -> None:
            self.call_from_thread(self._update_edit_log, idx, total, step.title, result)  # type: ignore[attr-defined]

        try:
            info = fetch_vm_info(vmid, adapter=get_proxmox_adapter())
            if info is None:
                fd, err_path = tempfile.mkstemp(prefix="edit_notfound_", suffix=".log")
                with open(fd, "w") as f:
                    f.write(f"VM {vmid} not found.\n")
                self.call_from_thread(self._finish_edit, False, Path(err_path))  # type: ignore[attr-defined]
                return

            create_snapshot(vmid)
            result = run_edit_worker(
                vmid, changes, start_after=start_after, on_step=on_step,
                current_config=info.config_raw,
            )
            self.call_from_thread(self._finish_edit, result.ok, result.log_path)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            log.exception("Unexpected error in edit worker: %s", exc)
            try:
                fd, err_path = tempfile.mkstemp(prefix="edit_error_", suffix=".log")
                with open(fd, "w") as f:
                    traceback.print_exc(file=f)
            except Exception:
                err_path = str(Path(tempfile.gettempdir()) / "edit_error.log")
            self.call_from_thread(self._finish_edit, False, Path(err_path))  # type: ignore[attr-defined]

    def _update_edit_log(self, idx: int, total: int, title: str, result: StepResult | None) -> None:
        if result is None:
            self.state.edit_log.append(f"Running {idx}/{total}: {title}")  # type: ignore[attr-defined]
        else:
            status = "OK" if result.ok else "FAIL"
            self.state.edit_log.append(f"{status} {idx}/{total}: {title}")  # type: ignore[attr-defined]
        visible = self.state.edit_log[-10:]  # type: ignore[attr-defined]
        self.query_one("#edit_log", Static).update("\n".join(visible))

    def _finish_edit(self, ok: bool, log_path: Path) -> None:
        self.state.edit_running = False  # type: ignore[attr-defined]
        self.state.edit_done = True  # type: ignore[attr-defined]
        self.state.edit_ok = ok  # type: ignore[attr-defined]
        if ok:
            # Clear form fields so re-clicking Apply doesn't re-apply (disk resize is non-idempotent)
            for sel in ("#edit_name", "#edit_cores", "#edit_memory", "#edit_bridge", "#edit_disk_add"):
                self.query_one(sel, Input).value = ""
            self.query_one("#edit_verbose_boot", Select).value = VERBOSE_BOOT_KEEP
            self.query_one("#edit_gpu", Select).clear()  # back to "Keep unchanged"
            for sel in ("#edit_gpu_address", "#edit_usb_manual"):
                self.query_one(sel, Input).value = ""
            # The VM's devices have just changed, so what the panel shows is
            # stale: re-read it rather than leave the tick boxes lying.
            self.state.edit_loaded_vmid = None
            try:
                self._refresh_edit_vm_devices(int(self.query_one("#edit_vmid", Input).value.strip()))
            except ValueError:
                pass
        self._validate_edit_form()
        result_box = self.query_one("#edit_result", Static)
        result_box.remove_class("hidden")
        if ok:
            result_box.remove_class("edit_result_fail")
            result_box.update(f"Changes applied.\nLog: {log_path}")
            self._refresh_vm_list()
        else:
            result_box.add_class("edit_result_fail")
            result_box.update(f"Failed to apply changes.\nLog: {log_path}")
