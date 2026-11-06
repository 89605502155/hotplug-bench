#!/usr/bin/env python3
"""Experiment 2. virtio-mem shrink under guest fragmentation.

virtio-mem lets the host set a target size; the guest driver plugs or
unplugs memory in small blocks to reach it. Growth is reliable. Shrinking
is best-effort: to unplug a block the driver must assemble a contiguous,
fully movable sub-block. Unmovable kernel allocations scattered over the
plugged region leave blocks that cannot be returned, so the achieved size
stays above the requested size. The gap is the quantity of interest.

Procedure, for each fragmentation level f:
  1. grow to PLUG_MB and online the new blocks;
  2. create f thousand files on tmpfs (unmovable inode/dentry slab) spread
     over the plugged memory, then free any anonymous ballast;
  3. request shrink back to 0 and watch the plugged "size" property;
  4. record requested vs achieved size and the residual gap.

Isolation: one tiny guest at a time, host memory checked before start.
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


def online_new_blocks(agent):
    """Online every offline memory block (virtio-mem adds them offline)."""
    return agent.out(
        "n=0; for b in /sys/devices/system/memory/memory*; do "
        "  [ \"$(cat $b/state)\" = offline ] && "
        "  echo online > $b/state 2>/dev/null && n=$((n+1)); done; "
        "echo $n")


def run_trial(frag_k, rep, log):
    need = BASE_MB + WINDOW_MB + 128 + 220
    wait_for_memory(need, log=log)
    rec = {"plug_mb": PLUG_MB, "frag_k": frag_k, "rep": rep}
    with SandboxVM(base_mb=BASE_MB, maxmem_mb=BASE_MB + WINDOW_MB + 64,
                   virtio_mem_mb=WINDOW_MB, vm_block_mb=2,
                   cmdline="init_on_alloc=0", log=log) as vm:
        rec["boot_s"] = round(vm.boot_s, 2)
        vmc = VirtioMemControl(vm)
        # 1. grow
        vmc.set_requested(PLUG_MB)
        plugged, ok = vmc.wait_size(PLUG_MB, 20)
        rec["grow_ok"] = ok
        rec["grown_mb"] = round(plugged)
        onl = online_new_blocks(vm.agent)
        rec["onlined_blocks"] = int(onl)
        rec["memtotal_after_grow"] = _memtotal(vm.agent)
        # 2. fragment with unmovable slab, then free anonymous ballast
        rec["files_made"] = 0
        if frag_k:
            # The default tmpfs inode limit (~17k here) would cap the load.
            vm.agent.run("mount -o remount,nr_inodes=1000000 /mnt/t")
            _, text = vm.agent.run(f"/bin/memload frag 32 {frag_k*1000} /mnt/t",
                                   timeout=90)
            made = [ln.split()[1] for ln in text.splitlines()
                    if ln.startswith("FILES ")]
            rec["files_made"] = int(made[0]) if made else -1
        rec["slab_kb"] = _slab(vm.agent)
        # 3. request shrink to zero
        rss_before = vm.rss_mb()
        vmc.set_requested(0)
        achieved, reached = vmc.wait_size(0, 15)
        rec["requested_mb"] = 0
        rec["achieved_mb"] = round(achieved, 1)
        rec["residual_mb"] = round(achieved, 1)
        rec["fully_returned"] = reached
        rec["rss_before_shrink"] = round(rss_before)
        rec["rss_after_shrink"] = round(vm.rss_mb())
        vm.keep_logs(os.path.join(RESULTS, f"exp2_frag{frag_k}_r{rep}"))
    return rec


def _memtotal(agent):
    return int(agent.out("grep MemTotal /proc/meminfo").split()[1]) // 1024


def _slab(agent):
    try:
        return int(agent.out("grep -E '^Slab:' /proc/meminfo").split()[1])
    except Exception:
        return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frags", default="0,20,60,120",
                    help="fragmentation levels, thousands of files")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--append", action="store_true",
                    help="load existing results and add/replace by frag level")
    args = ap.parse_args()
    os.makedirs(RESULTS, exist_ok=True)
    out_path = os.path.join(RESULTS, "exp2_virtio_mem_frag.json")
    rows = []
    if args.append and os.path.exists(out_path):
        rows = json.load(open(out_path))
    trials = [(int(f), r) for f in args.frags.split(",")
              for r in range(args.repeats)]
    for f, rep in trials:
        print(f"=== trial: frag={f}k files rep={rep} ===", flush=True)
        rec = run_trial(f, rep, log=lambda m: print(" ", m, flush=True))
        print("   ", json.dumps(rec, ensure_ascii=False), flush=True)
        rows = [r for r in rows
                if (r.get("frag_k"), r.get("rep", 0)) != (f, rep)] + [rec]
        rows.sort(key=lambda r: (r["frag_k"], r.get("rep", 0)))
        with open(out_path, "w") as fp:
            json.dump(rows, fp, ensure_ascii=False, indent=2)
    print("saved", os.path.join(RESULTS, "exp2_virtio_mem_frag.json"))


if __name__ == "__main__":
    main()
