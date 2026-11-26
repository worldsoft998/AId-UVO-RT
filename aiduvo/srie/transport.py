"""Transports: how Python talks to a live simulator.

Four implementations, in order of intrusiveness (all of them leave RTL, TB and
UVM source untouched):

``QuestaPipeTransport``
    Launches ``vsim -c`` and speaks Tcl over stdin/stdout.  Zero setup, works on
    every QuestaSim release on Windows and Linux.

``QuestaTclSocketTransport``
    Connects to a Tcl socket server running *inside* the simulator
    (``srie_bootstrap.do -server <port>``).  Same command set, but the simulator
    can also push unsolicited events, and several clients can attach.

``FLITransport`` (optional, see :mod:`aiduvo.srie.fli_bridge`)
    Direct Foreign Language Interface access through a small C shim compiled
    once with the Questa headers.  Lowest latency, value-change callbacks.

``MockTransport``
    An in-process synthetic simulator used for self-tests, CI and demos.  It
    speaks the exact same wire protocol, so the rest of the framework cannot
    tell the difference.
"""

from __future__ import annotations

import collections
import os
import queue
import shlex
import socket
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence

from aiduvo.srie.protocol import (
    FATAL_PREFIX,
    READY_PREFIX,
    CommandResult,
    Event,
    TransportError,
    is_noise,
    parse_end_line,
    parse_event_line,
)

_WRAP = (
    "if {{[catch {{{cmd}}} __srie_out]}} "
    '{{puts "@@SRIE_ERR $__srie_out@@"; set __srie_rc 1}} else {{set __srie_rc 0}}; '
    "puts $__srie_out; "
    'puts "@@SRIE_END {cid} rc=$__srie_rc@@"'
)


class Transport(ABC):
    """Abstract command channel to a simulator."""

    name = "abstract"

    def __init__(self) -> None:
        self._lines: "queue.Queue[Optional[str]]" = queue.Queue()
        self._events: Deque[Event] = collections.deque()
        self._evt_lock = threading.Lock()
        self._cmd_lock = threading.RLock()
        self._alive = False
        self._ready = threading.Event()
        self._fatal = ""
        self.version = ""
        self._id = 0
        self._reader: Optional[threading.Thread] = None

    # ------------------------------------------------------------------ lifecycle
    @abstractmethod
    def start(self, timeout: float = 120.0) -> None: ...

    @abstractmethod
    def _send(self, command: str, cid: int) -> None: ...

    def close(self) -> None: ...

    def is_alive(self) -> bool:
        return self._alive

    @property
    def fatal_error(self) -> str:
        return self._fatal

    # ------------------------------------------------------------------- reading
    def _handle_line(self, line: str) -> None:
        if line.startswith(READY_PREFIX):
            self.version = line[len(READY_PREFIX) :].strip().strip("@").strip()
            self._ready.set()
            return
        if line.startswith(FATAL_PREFIX):
            self._fatal = line[len(FATAL_PREFIX) :].strip().rstrip("@").strip()
            self._lines.put(None)
            self._ready.set()
            return
        evt = parse_event_line(line)
        if evt is not None:
            with self._evt_lock:
                self._events.append(evt)
            return
        self._lines.put(line)

    def _read_loop(self, stream: Iterable[str]) -> None:
        try:
            for line in stream:
                self._handle_line(line.rstrip("\r\n"))
        except Exception as exc:  # pragma: no cover - platform dependent
            self._fatal = self._fatal or f"reader stopped: {exc}"
        finally:
            self._alive = False
            self._lines.put(None)

    def wait_ready(self, timeout: float = 120.0) -> str:
        if not self._ready.wait(timeout):
            raise TransportError(f"{self.name}: simulator did not report ready within {timeout}s")
        if self._fatal:
            raise TransportError(f"{self.name}: simulator fatal error: {self._fatal}")
        return self.version

    # ---------------------------------------------------------------- execution
    def execute(self, command: str, timeout: float = 180.0) -> CommandResult:
        """Send one Tcl command and collect its output up to the sentinel."""
        if not self._alive:
            raise TransportError(f"{self.name}: transport is not running")
        t0 = time.time()
        with self._cmd_lock:
            self._id += 1
            cid = self._id
            self._drain_stale()
            self._send(command, cid)
            buf: List[str] = []
            err: List[str] = []
            deadline = t0 + timeout
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TransportError(f"{self.name}: timeout waiting for {command!r}")
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty:
                    raise TransportError(f"{self.name}: timeout waiting for {command!r}")
                if line is None:
                    raise TransportError(
                        f"{self.name}: simulator exited while running {command!r} "
                        f"({self._fatal or 'no error text'})"
                    )
                if line.startswith("@@SRIE_ERR "):
                    err.append(line[len("@@SRIE_ERR ") :].rstrip("@"))
                    continue
                end = parse_end_line(line)
                if end is not None and end[0] == cid:
                    ok = end[1] and not err
                    return CommandResult(
                        ok=ok,
                        stdout="\n".join(buf),
                        error="\n".join(err),
                        elapsed=time.time() - t0,
                        command=command,
                    )
                if is_noise(line) or not line.strip():
                    continue
                buf.append(line)

    def _drain_stale(self) -> None:
        while True:
            try:
                self._lines.get_nowait()
            except queue.Empty:
                return

    def poll_events(self, max_events: int = 512) -> List[Event]:
        out: List[Event] = []
        with self._evt_lock:
            while self._events and len(out) < max_events:
                out.append(self._events.popleft())
        return out

    def peek_events(self) -> int:
        with self._evt_lock:
            return len(self._events)

    def info(self) -> Dict[str, Any]:
        return {"transport": self.name, "version": self.version, "alive": self._alive}


# ---------------------------------------------------------------------------
# 1. vsim -c over pipes
# ---------------------------------------------------------------------------


class QuestaPipeTransport(Transport):
    """Drive ``vsim -c`` through stdin/stdout."""

    name = "questa-pipe"

    def __init__(
        self,
        argv: Sequence[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        startup_timeout: float = 180.0,
    ):
        super().__init__()
        self.argv = list(argv)
        self.cwd = cwd
        self.env = {**os.environ, **(env or {})}
        self.startup_timeout = startup_timeout
        self._proc: Optional[subprocess.Popen] = None

    def start(self, timeout: float = 180.0) -> None:
        kwargs: Dict[str, Any] = dict(
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=1,
            universal_newlines=True,
            cwd=self.cwd,
            env=self.env,
        )
        if os.name == "nt":  # pragma: no cover - Windows only
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        self._proc = subprocess.Popen(self.argv, **kwargs)  # type: ignore[arg-type]
        self._alive = True
        assert self._proc.stdout is not None
        self._reader = threading.Thread(
            target=self._read_loop, args=(self._proc.stdout,), name="srie-reader", daemon=True
        )
        self._reader.start()
        self.wait_ready(timeout)

    def _send(self, command: str, cid: int) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise TransportError("questa-pipe: process not started")
        payload = _WRAP.format(cmd=command.replace("\n", " "), cid=cid)
        try:
            self._proc.stdin.write(payload + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self._alive = False
            raise TransportError(f"questa-pipe: write failed: {exc}") from exc

    def close(self) -> None:
        self._alive = False
        if self._proc is None:
            return
        try:
            if self._proc.poll() is None:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=10)
                except subprocess.TimeoutExpired:  # pragma: no cover
                    self._proc.kill()
        except OSError:  # pragma: no cover
            pass

    def is_alive(self) -> bool:
        return self._alive and self._proc is not None and self._proc.poll() is None

    def info(self) -> Dict[str, Any]:
        d = super().info()
        d["argv"] = self.argv
        d["pid"] = getattr(self._proc, "pid", None)
        return d


# ---------------------------------------------------------------------------
# 2. Tcl socket server inside the simulator
# ---------------------------------------------------------------------------


class QuestaTclSocketTransport(Transport):
    """Connect to the Tcl server started by ``srie_bootstrap.do -server <port>``."""

    name = "questa-socket"

    def __init__(self, host: str = "127.0.0.1", port: int = 0,
                 connect_timeout: float = 30.0, retries: int = 60):
        super().__init__()
        self.host = host
        self.port = int(port)
        self.connect_timeout = connect_timeout
        self.retries = retries
        self._sock: Optional[socket.socket] = None
        self._file = None

    def start(self, timeout: float = 120.0) -> None:
        last: Optional[Exception] = None
        deadline = time.time() + max(timeout, self.connect_timeout)
        while time.time() < deadline:
            try:
                self._sock = socket.create_connection((self.host, self.port), timeout=5.0)
                break
            except OSError as exc:  # simulator not listening yet
                last = exc
                time.sleep(0.5)
        if self._sock is None:
            raise TransportError(f"questa-socket: cannot connect to {self.host}:{self.port} ({last})")
        self._sock.settimeout(None)
        self._file = self._sock.makefile("r", encoding="utf-8", newline="\n")
        self._alive = True
        self._reader = threading.Thread(target=self._read_loop, args=(self._file,), name="srie-sock", daemon=True)
        self._reader.start()
        self.wait_ready(timeout)

    def _send(self, command: str, cid: int) -> None:
        if self._sock is None:
            raise TransportError("questa-socket: not connected")
        try:
            # The Tcl server splits "<cid>\t<command>" so it can echo the right sentinel.
            payload = f"{cid}\t{command.replace(chr(10), ' ')}\n"
            self._sock.sendall(payload.encode("utf-8"))
        except OSError as exc:
            self._alive = False
            raise TransportError(f"questa-socket: send failed: {exc}") from exc

    def close(self) -> None:
        self._alive = False
        try:
            if self._file is not None:
                self._file.close()
            if self._sock is not None:
                self._sock.close()
        except OSError:  # pragma: no cover
            pass


# ---------------------------------------------------------------------------
# 3. Mock (synthetic, in-process) simulator
# ---------------------------------------------------------------------------


class MockTransport(Transport):
    """Synthetic simulator speaking the real wire protocol (self-tests, demos)."""

    name = "mock"

    def __init__(self, sim: Any = None, seed: int = 1):
        super().__init__()
        if sim is None:
            from aiduvo.srie.mock import MockQuestaSim

            sim = MockQuestaSim(seed=seed)
        self.sim = sim

    def start(self, timeout: float = 30.0) -> None:
        self._alive = True
        self.version = self.sim.version
        self._handle_line(f"{READY_PREFIX} {self.sim.version}@@")

    def _send(self, command: str, cid: int) -> None:
        for line in self.sim.execute_lines(command, cid):
            self._handle_line(line)

    def close(self) -> None:
        self._alive = False

    def is_alive(self) -> bool:
        return self._alive

    def info(self) -> Dict[str, Any]:
        d = super().info()
        d["design"] = self.sim.describe_design()
        return d


def make_transport(spec: Dict[str, Any]) -> Transport:
    """Build a transport from a config dict.

    ``spec`` keys: ``kind`` (``pipe`` | ``socket`` | ``mock`` | ``fli``), plus
    ``argv``/``cwd``/``env`` for pipe, ``host``/``port`` for socket.
    """
    kind = str(spec.get("kind", "mock")).lower()
    if kind in ("pipe", "questa", "vsim"):
        return QuestaPipeTransport(
            argv=spec.get("argv") or [],
            cwd=spec.get("cwd"),
            env=spec.get("env"),
        )
    if kind in ("socket", "tcl"):
        return QuestaTclSocketTransport(
            host=spec.get("host", "127.0.0.1"), port=int(spec.get("port", 0) or 0)
        )
    if kind == "mock":
        return MockTransport(seed=int(spec.get("seed", 1) or 1))
    if kind == "fli":
        from aiduvo.srie.fli_bridge import FLITransport

        return FLITransport(library=spec.get("library", ""), design=spec.get("design", ""))
    raise ValueError(f"unknown transport kind {kind!r}")


def split_argv(text: str) -> List[str]:
    """Split a command line respecting quotes (Windows-style is good enough)."""
    return shlex.split(text, posix=(os.name != "nt"))
