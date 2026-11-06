"""Minimal synchronous QMP client (QEMU Machine Protocol)."""

import json
import socket
import time


class QMPError(RuntimeError):
    pass


class QMP:
    def __init__(self, path, timeout=30.0):
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
        self.events = []
        self._read()  # greeting
        self.cmd("qmp_capabilities")

    def _read_line(self, timeout=None):
        self.sock.settimeout(timeout)
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise QMPError("QMP connection closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line

    def _read(self, timeout=None):
        return json.loads(self._read_line(timeout))

    def cmd(self, name, **args):
        msg = {"execute": name}
        if args:
            msg["arguments"] = args
        self.sock.settimeout(None)
        self.sock.sendall(json.dumps(msg).encode() + b"\n")
        while True:
            reply = self._read()
            if "event" in reply:
                reply["t_host"] = time.monotonic()
                self.events.append(reply)
                continue
            if "error" in reply:
                raise QMPError(f"{name}: {reply['error'].get('desc')}")
            return reply.get("return")

    def poll_events(self, timeout=0.0):
        """Collect asynchronous events that arrived within ``timeout``."""
        try:
            while True:
                ev = self._read(timeout if timeout > 0 else 0.001)
                ev["t_host"] = time.monotonic()
                self.events.append(ev)
        except (socket.timeout, BlockingIOError, TimeoutError):
            pass
        finally:
            self.sock.settimeout(None)
        return self.events

    def take_event(self, name):
        for i, ev in enumerate(self.events):
            if ev.get("event") == name:
                return self.events.pop(i)
        return None

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass
