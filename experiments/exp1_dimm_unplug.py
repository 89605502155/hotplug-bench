#!/usr/bin/env python3
"""Experiment 1. Hot-unplug of an ACPI pc-dimm under load.

A DIMM is plugged into a running guest and brought online in one of two
policies:

  online          the block joins a normal (non-movable) zone; kernel
                  allocations may land on it and pin it;
  online_movable  the block joins ZONE_MOVABLE; only movable pages are
                  allowed there, so the kernel can always migrate them out.

After the block is online the guest fills it with a workload, then the host
requests the DIMM back (device_del) and waits for DEVICE_DELETED. We record
whether the eject completes within the timeout and how long it takes.

The result is the asymmetry the paper warns about: in the "online" policy a
single unmovable page blocks the eject forever, and QEMU neither times out
nor reports an error -- the request simply never completes.

Memory discipline: a single tiny guest (<=256 MiB base + one 128 MiB DIMM),
one trial at a time, host memory checked before each VM start.
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hpbench.vm import SandboxVM, wait_for_memory  # noqa: E402
from hpbench.hotplug import DimmControl  # noqa: E402

DIMM_MB = 128
RESULTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "results")


def online_block(agent, policy):
    """Online the just-added offline memory block with the given policy.

    Returns the block name, or None if no offline block appeared.
    """
    blocks = agent.out(
        "for b in /sys/devices/system/memory/memory*; do "
        "  s=$(cat $b/state 2>/dev/null); "
        "  [ \"$s\" = offline ] && echo ${b##*/memory}; done; true").split()
    if not blocks:
        return None
    blk = blocks[0]
    target = "online_movable" if policy == "online_movable" else "online"
    rc, out = agent.run(
        f"echo {target} > /sys/devices/system/memory/memory{blk}/state")
    return blk if rc == 0 else None


def fill_block(agent, mb):
    """Put a realistic, moderate load on the guest after the DIMM is online.

    The discriminating factor between the two policies is unmovable kernel
    memory. We create many small files on tmpfs: each pins an inode and a
    dentry in kernel slab, which is unmovable and may land anywhere in a
    normal-zone block, including the fresh DIMM. In a movable-zone block
    such allocations are refused by the allocator, so the block stays
    evictable. We also touch and immediately release some anonymous memory
    to populate and then free pages on the block, leaving it fragmented but
    not full, so that migration has somewhere to go.
    """
    agent.run("/bin/memload slab 40000 /mnt/t", timeout=60)
    agent.run(f"/bin/memload frag {mb // 2} 10000 /mnt/t", timeout=60)


def run_trial(policy, unplug_timeout, log):
    need = 256 + DIMM_MB + 128 + 220
    wait_for_memory(need, log=log)
    rec = {"policy": policy, "dimm_mb": DIMM_MB}
    with SandboxVM(base_mb=256, slots=2, maxmem_mb=256 + DIMM_MB + 64,
                   cmdline="init_on_alloc=0 memhp_default_state=offline", log=log) as vm:
        rec["boot_s"] = round(vm.boot_s, 2)
        dimm = DimmControl(vm)
        did, mid, plug_s = dimm.plug(DIMM_MB, policy)
        rec["plug_s"] = round(plug_s, 3)
        time.sleep(1.0)
        blk = online_block(vm.agent, policy)
        rec["onlined"] = blk is not None
        rec["online_state"] = vm.agent.out(
            f"cat /sys/devices/system/memory/memory{blk}/state") if blk else ""
        fill_block(vm.agent, DIMM_MB - 16)
        rec["mem_before"] = _memfree(vm.agent)
        rec["rss_before"] = round(vm.rss_mb())

        t0 = dimm.request_unplug(did)
        t_done = dimm.wait_deleted(did, unplug_timeout)
        if t_done is None:
            rec["unplug_completed"] = False
            rec["unplug_s"] = None
            rec["offline_state"] = vm.agent.out(
                f"cat /sys/devices/system/memory/memory{blk}/state"
                if blk else "echo n/a")
        else:
            rec["unplug_completed"] = True
            rec["unplug_s"] = round(t_done - t0, 3)
        rec["kmsg"] = vm.agent.out(
            "dmesg 2>/dev/null | grep -iE 'offline|movable|isolate' | tail -3")
        rec["rss_after"] = round(vm.rss_mb())
        vm.keep_logs(os.path.join(RESULTS, f"exp1_{policy}"))
    return rec


def _memfree(agent):
    out = agent.out("grep MemFree /proc/meminfo")
    return int(out.split()[1]) // 1024


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeout", type=float, default=25.0,
                    help="seconds to wait for the eject to complete")
    ap.add_argument("--policies", default="online_movable,online")
    ap.add_argument("--repeats", type=int, default=3)
    args = ap.parse_args()
    os.makedirs(RESULTS, exist_ok=True)
    rows = []
    for policy in args.policies.split(","):
        for r in range(args.repeats):
            print(f"=== trial: policy={policy} repeat={r} ===", flush=True)
            rec = run_trial(policy, args.timeout,
                            log=lambda m: print(" ", m, flush=True))
            rec["repeat"] = r
            print("   ", json.dumps(rec, ensure_ascii=False), flush=True)
            rows.append(rec)
    with open(os.path.join(RESULTS, "exp1_dimm_unplug.json"), "w") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    print("saved", os.path.join(RESULTS, "exp1_dimm_unplug.json"))


if __name__ == "__main__":
    main()
