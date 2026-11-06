"""Hotplug operations driven over QMP, with host-side timing.

Both paths exercise the real QEMU hotplug code:

* ACPI pc-dimm: ``object-add`` (memory-backend-ram) + ``device_add pc-dimm``
  to plug, ``device_del`` to request eject. Completion of an eject is the
  ``DEVICE_DELETED`` event; QEMU raises no event and sets no timeout when the
  guest never completes the eject, which is the point of experiment 1.
* virtio-mem: a ``virtio-mem-pci`` device is present from boot; its
  ``requested-size`` property sets the target, and the ``size`` property
  reports how much the guest has actually plugged.
"""

import time


class DimmControl:
    def __init__(self, vm):
        self.vm = vm
        self.n = 0

    def plug(self, size_mb, policy="online_movable"):
        """Add one pc-dimm; return (id, host seconds to DEVICE event seen)."""
        self.n += 1
        mid, did = f"mem{self.n}", f"dimm{self.n}"
        self.vm.qmp.cmd("object-add", **{
            "qom-type": "memory-backend-ram", "id": mid,
            "size": size_mb * 1024 * 1024})
        t0 = time.monotonic()
        self.vm.qmp.cmd("device_add", driver="pc-dimm", id=did, memdev=mid)
        return did, mid, time.monotonic() - t0

    def request_unplug(self, did):
        t0 = time.monotonic()
        self.vm.qmp.cmd("device_del", id=did)
        return t0

    def wait_deleted(self, did, timeout):
        """Wait for DEVICE_DELETED for ``did``. Return seconds or None."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.vm.qmp.poll_events(0.2)
            for ev in list(self.vm.qmp.events):
                if (ev.get("event") == "DEVICE_DELETED"
                        and ev.get("data", {}).get("device") == did):
                    self.vm.qmp.events.remove(ev)
                    return ev["t_host"]
        return None


class VirtioMemControl:
    def __init__(self, vm, dev_id="vm0"):
        self.vm = vm
        self.dev_id = dev_id

    def _qom(self, prop):
        return self.vm.qmp.cmd("qom-get", path=self.dev_id, property=prop)

    def set_requested(self, size_mb):
        self.vm.qmp.cmd("qom-set", path=self.dev_id,
                        property="requested-size",
                        value=size_mb * 1024 * 1024)

    def requested_mb(self):
        return self._qom("requested-size") / 1024 / 1024

    def size_mb(self):
        """Currently plugged size the guest has accepted."""
        return self._qom("size") / 1024 / 1024

    def wait_size(self, target_mb, timeout, tol_mb=1):
        """Wait until plugged size reaches target (±tol) or timeout."""
        deadline = time.monotonic() + timeout
        last = self.size_mb()
        while time.monotonic() < deadline:
            cur = self.size_mb()
            if abs(cur - target_mb) <= tol_mb:
                return cur, True
            last = cur
            time.sleep(0.25)
        return last, False
