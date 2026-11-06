#!/usr/bin/env python3
"""Experiment 3. How much memory the host can actually reclaim.

Every cooperative hotplug mechanism depends on the guest to carry out the
request. The host cannot force the result. We measure the gap between what
the host asks virtio-mem to return and what it really gets back, as the
resident set size (RSS) of the QEMU process on the host -- the memory the
host truly pays for -- for three guest behaviours:

  cooperative    stock guest: driver loaded; a process touches the plugged
                 memory and exits before the shrink, so the memory is
                 free and shrink should return almost everything;
  no_driver      guest never loads the virtio_mem module: the host raises
                 the device's requested size, but nothing happens inside;
  busy           driver loaded, but a guest process keeps the touched
                 memory allocated during the shrink, so the driver has to
                 migrate it into base memory or leave blocks plugged.

The host-visible RSS before and after the shrink request quantifies the
residual the host cannot recover. This is the central risk for an adaptive
controller: a shrink command is an advisory, not a guarantee.

Isolation: one guest at a time; host memory checked before each start;
the load size is bounded well under the guest budget.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hpbench.vm import SandboxVM, wait_for_memory  # noqa: E402
from hpbench.hotplug import VirtioMemControl  # noqa: E402

BASE_MB = 256
PLUG_MB = 128
WINDOW_MB = 256
RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results")


def run_trial(mode, rep, log):
    need = BASE_MB + WINDOW_MB + 128 + 220
    wait_for_memory(need, log=log)
    load_driver = mode != "no_driver"
    rec = {"mode": mode, "rep": rep, "plug_mb": PLUG_MB,
           "load_mb": PLUG_MB - 24}
    with SandboxVM(base_mb=BASE_MB, maxmem_mb=BASE_MB + WINDOW_MB + 64,
                   virtio_mem_mb=WINDOW_MB, vm_block_mb=2,
                   cmdline="init_on_alloc=0", log=log) as vm:
        if not load_driver:
            # Undo the module load the init script performed.
            vm.agent.run("rmmod virtio_mem 2>/dev/null; true")
        rec["driver_loaded"] = bool(int(
            vm.agent.out("[ -d /sys/module/virtio_mem ] && echo 1 || echo 0")))
        vmc = VirtioMemControl(vm)
        rec["rss_idle"] = round(vm.rss_mb())

        # grow to PLUG_MB
        vmc.set_requested(PLUG_MB)
        grown, grow_ok = vmc.wait_size(PLUG_MB, 12)
        rec["grown_mb"] = round(grown, 1)
        rec["grow_ok"] = grow_ok
        rec["grow_gap_mb"] = round(PLUG_MB - grown, 1)

        if mode in ("cooperative", "busy") and rec["driver_loaded"]:
            # Touch most of the just-added memory; "cooperative" frees it
            # again before the shrink, "busy" keeps holding it.
            vm.agent.out(
                f"/bin/memload anon {PLUG_MB - 24} >/tmp/a.log 2>&1 & "
                f"i=0; while [ ! -s /tmp/a.log ] && [ $i -lt 100 ]; do "
                f"usleep 50000 2>/dev/null || sleep 1; i=$((i+1)); done",
                timeout=40)
            if mode == "cooperative":
                vm.agent.run("killall memload; sleep 1")
        rec["rss_grown"] = round(vm.rss_mb())

        # ask for everything back
        vmc.set_requested(0)
        achieved, reached = vmc.wait_size(0, 15)
        time.sleep(1.0)
        rec["requested_mb"] = 0
        rec["achieved_size_mb"] = round(achieved, 1)
        rec["fully_returned"] = reached
        rec["rss_after_shrink"] = round(vm.rss_mb())
        rec["host_reclaimed_mb"] = round(rec["rss_grown"] - rec["rss_after_shrink"])
        rec["rss_retained_mb"] = round(rec["rss_after_shrink"] - rec["rss_idle"])
        vm.keep_logs(os.path.join(RESULTS, f"exp3_{mode}_r{rep}"))
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default="cooperative,no_driver,busy")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    os.makedirs(RESULTS, exist_ok=True)
    rows = []
    trials = [(m, r) for m in args.modes.split(",") for r in range(args.repeats)]
    for mode, rep in trials:
        print(f"=== trial: mode={mode} rep={rep} ===", flush=True)
        rec = run_trial(mode, rep, log=lambda m: print(" ", m, flush=True))
        print("   ", json.dumps(rec, ensure_ascii=False), flush=True)
        rows.append(rec)
        with open(os.path.join(RESULTS, "exp3_uncooperative.json"), "w") as fp:
            json.dump(rows, fp, ensure_ascii=False, indent=2)
    print("saved", os.path.join(RESULTS, "exp3_uncooperative.json"))


if __name__ == "__main__":
    main()
