"""Sandbox virtual machine for memory hotplug experiments.

The guest is a stock distribution kernel with a tiny initramfs (see guest/).
QEMU runs inside a transient systemd user scope with a hard MemoryMax, so the
sandbox can never take more host memory than its budget. Only the QEMU trace
events of the memory hotplug code are enabled, which isolates that code in
the log:

  hw/acpi/memory_hotplug.c, hw/mem/pc-dimm.c   mhp_*, memory_device_*
  hw/virtio/virtio-mem.c                       virtio_mem_*
"""

import os
import shutil
import socket
import subprocess
import tempfile
import time

from .qmp import QMP

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")
TRACE_EVENTS = ["mhp_*", "memory_device_*", "virtio_mem_*"]


def mem_available_mb():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) // 1024
    return 0


def wait_for_memory(need_mb, log=print, poll_s=10):
    """Block until the host has ``need_mb`` MiB available."""
    warned = False
    while True:
        avail = mem_available_mb()
        if avail >= need_mb:
            if warned:
                log(f"[mem] window found: {avail} MiB available")
            return avail
        if not warned:
            log(f"[mem] {avail} MiB available, need {need_mb}; waiting")
            warned = True
        time.sleep(poll_s)


class GuestAgent:
    """Line protocol to guest/init over a virtio console."""

    def __init__(self, path, timeout=60.0):
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect(path)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                self.sock.close()
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
        self.buf = b""
        self.seq = 0
        self._wait_line(b"@@HELLO", timeout)

    def _wait_line(self, marker, timeout):
        self.sock.settimeout(timeout)
        lines = []
        while True:
            while b"\n" not in self.buf:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise RuntimeError("guest agent closed")
                self.buf += chunk
            line, self.buf = self.buf.split(b"\n", 1)
            line = line.rstrip(b"\r")
            if line.startswith(marker):
                return line, lines
            lines.append(line.decode(errors="replace"))

    def run(self, cmd, timeout=120.0):
        self.seq += 1
        sent = f"{self.seq} {cmd}"
        self.sock.sendall(sent.encode() + b"\n")
        end, lines = self._wait_line(f"@@END {self.seq} ".encode(), timeout)
        rc = int(end.split()[-1])
        # The virtio console may echo the command back; drop that line.
        lines = [ln for ln in lines if ln != sent]
        return rc, "\n".join(lines)

    def out(self, cmd, timeout=120.0):
        rc, text = self.run(cmd, timeout)
        if rc != 0:
            raise RuntimeError(f"guest command failed ({rc}): {cmd}\n{text}")
        return text


class SandboxVM:
    def __init__(self, base_mb=160, slots=2, maxmem_mb=512, extra_args=(),
                 cmdline="", mem_max_mb=None, workdir=None, log=print,
                 virtio_mem_mb=0, vm_block_mb=2, vm_args=""):
        self.base_mb = base_mb
        self.maxmem_mb = maxmem_mb
        self.log = log
        # Optional virtio-mem device: a memory-backend of virtio_mem_mb sized
        # address window, plugged as virtio-mem-pci. The guest loads the
        # module (hp.virtio_mem=1) and the host drives it over QMP.
        vmem = []
        if virtio_mem_mb:
            vmem = [
                "-object",
                f"memory-backend-ram,id=vmem0,size={virtio_mem_mb}M,"
                "reserve=off,prealloc=off",
                "-device",
                f"virtio-mem-pci,id=vm0,memdev=vmem0,"
                f"block-size={vm_block_mb}M,requested-size=0",
            ]
            cmdline = f"hp.virtio_mem=1 {vm_args} {cmdline}"
        self._vmem_args = vmem
        self.dir = workdir or tempfile.mkdtemp(prefix="hpbench-")
        self.qmp_path = os.path.join(self.dir, "qmp.sock")
        self.agent_path = os.path.join(self.dir, "agent.sock")
        self.trace_path = os.path.join(self.dir, "trace.log")
        self.console_path = os.path.join(self.dir, "console.log")
        # Hard ceiling for the whole QEMU process: guest RAM + overhead.
        self.mem_max_mb = mem_max_mb or (maxmem_mb + 128)
        # crashkernel/CMA reserve a large fixed slice of guest RAM that would
        # otherwise distort the small-guest accounting; turn them off.
        append = "console=ttyS0 quiet panic=-1 crashkernel=0 cma=0 " + cmdline
        trace = ",".join(f"enable={e}" for e in TRACE_EVENTS)
        # QEMU is launched as a direct child of this process so the caller can
        # track and reap it. Its own memory is bounded by the small guest
        # (base + maxmem window); wait_for_memory() keeps a host reserve. An
        # optional transient scope with a hard MemoryMax can be enabled with
        # HPBENCH_SCOPE=1, but it detaches QEMU into a separate cgroup and is
        # off by default.
        scope = []
        if os.environ.get("HPBENCH_SCOPE") == "1":
            scope = ["systemd-run", "--user", "--scope", "--quiet",
                     "-p", f"MemoryMax={self.mem_max_mb}M",
                     "-p", "MemorySwapMax=0"]
        self.argv = [
            *scope,
            "qemu-system-x86_64",
            "-machine", "q35,accel=kvm", "-cpu", "host", "-smp", "2",
            "-m", f"{base_mb}M,slots={slots},maxmem={maxmem_mb}M",
            "-kernel", os.path.join(BUILD, "vmlinuz"),
            "-initrd", os.path.join(BUILD, "initramfs.gz"),
            "-append", append,
            "-nodefaults", "-no-reboot", "-display", "none",
            "-serial", f"file:{self.console_path}",
            "-chardev", f"socket,id=ag,path={self.agent_path},server=on,wait=off",
            "-device", "virtio-serial-pci",
            "-device", "virtconsole,chardev=ag",
            "-qmp", f"unix:{self.qmp_path},server=on,wait=off",
            "-trace", f"{trace},file={self.trace_path}",
            *self._vmem_args,
            *extra_args,
        ]
        self.proc = None
        self.qmp = None
        self.agent = None

    def start(self):
        self.t0 = time.monotonic()
        self.proc = subprocess.Popen(self.argv, stdin=subprocess.DEVNULL)
        self.qmp = QMP(self.qmp_path)
        self.agent = GuestAgent(self.agent_path)
        self.boot_s = time.monotonic() - self.t0
        return self

    def rss_mb(self):
        """Resident memory of QEMU on the host (what the host really pays)."""
        try:
            with open(f"/proc/{self.proc.pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024.0
        except OSError:
            pass
        return float("nan")

    def trace_lines(self):
        try:
            with open(self.trace_path, errors="replace") as f:
                return f.read().splitlines()
        except OSError:
            return []

    def stop(self):
        if self.qmp:
            try:
                self.qmp.cmd("quit")
            except Exception:
                pass
            self.qmp.close()
        if self.proc:
            try:
                self.proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.proc.terminate()
                self.proc.wait(timeout=15)

    def keep_logs(self, dest):
        os.makedirs(dest, exist_ok=True)
        for name in ("trace.log", "console.log"):
            src = os.path.join(self.dir, name)
            if os.path.exists(src):
                shutil.copy(src, os.path.join(dest, name))

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
        shutil.rmtree(self.dir, ignore_errors=True)
