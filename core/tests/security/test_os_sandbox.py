"""OS-enforced network sandbox (Seatbelt profile shared with the desktop shell).

No test here contacts anything outside this machine: "remote" probes target 192.0.2.1
(TEST-NET-1, reserved for documentation) and are refused by the kernel before a packet is
sent; the DNS probe only touches the local resolver daemon's Unix socket.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from lazis.security.network_guard import os_network_sandbox_status
from tests.conftest import REPO_ROOT
from tests.process_helpers import start_backend

PROFILE = REPO_ROOT / "apps/desktop/src-tauri/sandbox/backend.sb"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or not Path(SANDBOX_EXEC).exists(),
    reason="macOS sandbox-exec not available",
)

TEST_NET = "192.0.2.1"

PROBE = rf"""
import ctypes, errno, json, os, socket, struct, subprocess, sys
from lazis.security.network_guard import os_network_sandbox_status
r = {{"status": os_network_sandbox_status()}}
def attempt(name, fn):
    try:
        fn(); r[name] = "allowed"
    except OSError as exc:
        r[name] = "eperm" if exc.errno in (errno.EPERM, errno.EACCES) else "error:" + str(exc.errno)
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
port = srv.getsockname()[1]
attempt("loopback_other_port", lambda: socket.create_connection(("127.0.0.1", port), timeout=2).close())
attempt("ollama_port", lambda: socket.create_connection(("127.0.0.1", 11434), timeout=2).close())
def py_remote():
    s = socket.socket(); s.settimeout(2)
    s.connect(("{TEST_NET}", 9))
attempt("python_socket_remote", py_remote)
def udp_remote():
    socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("{TEST_NET}", 9))
attempt("udp_remote", udp_remote)
libc = ctypes.CDLL(None, use_errno=True)
def native_remote():
    fd = libc.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
    sa = struct.pack("BBH4s8x", 16, socket.AF_INET, socket.htons(9), socket.inet_aton("{TEST_NET}"))
    if libc.connect(fd, sa, len(sa)) != 0:
        e = ctypes.get_errno(); raise OSError(e, os.strerror(e))
attempt("native_libc_remote", native_remote)
child = subprocess.run([sys.executable, "-c",
    "import socket,sys\ntry:\n s=socket.socket(); s.settimeout(2); s.connect(('{TEST_NET}', 9)); print('allowed')\n"
    "except OSError as e:\n print('eperm' if e.errno in (1, 13) else 'error:%s' % e.errno)"],
    capture_output=True, text=True)
r["child_process_remote"] = child.stdout.strip()
attempt("dns_daemon", lambda: socket.socket(socket.AF_UNIX).connect("/var/run/mDNSResponder"))
print(json.dumps(r))
"""


def _run_probe(*, sandboxed: bool) -> dict[str, str]:
    cmd = [sys.executable, "-c", PROBE]
    if sandboxed:
        cmd = [SANDBOX_EXEC, "-f", str(PROFILE), *cmd]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_profile_denies_every_path_to_other_hosts_and_local_services() -> None:
    r = _run_probe(sandboxed=True)
    assert r["status"] == "enforced"
    # Phase 2: only the local inference runtime's port is reachable. Whether Ollama is running
    # or not, the sandbox must not be what stops it (refused ≠ EPERM).
    assert r["ollama_port"] in ("allowed", "error:61"), r["ollama_port"]
    # Any other local service (a proxy, a debugger port, ...) is unreachable.
    assert r["loopback_other_port"] == "eperm"
    # The OS refuses, regardless of how the connection is attempted.
    for name in (
        "python_socket_remote",
        "udp_remote",
        "native_libc_remote",  # bypasses Python's socket module and the audit hook
        "child_process_remote",  # children inherit the profile
        "dns_daemon",  # no name resolution
    ):
        assert r[name] == "eperm", (name, r[name])


def test_status_probe_reports_not_enforced_without_the_profile() -> None:
    assert os_network_sandbox_status() == "not_enforced"
    assert os_network_sandbox_status("/nonexistent/socket") == "unknown"


def test_backend_runs_under_the_profile_and_reports_it(tmp_path: Path) -> None:
    backend = start_backend(
        tmp_path,
        prefix=[SANDBOX_EXEC, "-f", str(PROFILE)],
        extra_args=["--require-os-sandbox"],
    )
    try:
        assert backend.fatal is None, backend.outputs()
        status = backend.get("/api/v1/system/status").json()
        assert status["privacy"]["os_network_sandbox"] == "enforced"
        assert status["database"]["encryption_verified"] is True
        # The status call no longer starts `uname` (the guard would refuse it).
        assert backend.close_lifeline() == 0
        log = (backend.log_dir / "core.log").read_text()
        assert "security.policy_blocked" not in log
    finally:
        if backend.proc.poll() is None:
            backend.proc.kill()


def test_backend_refuses_to_start_when_the_sandbox_is_required_but_missing(
    tmp_path: Path,
) -> None:
    backend = start_backend(tmp_path, extra_args=["--require-os-sandbox"])
    assert backend.fatal is not None
    assert backend.fatal["code"] == "network_sandbox_unavailable"
    assert backend.proc.wait(10) == 3
    # It stopped before reading secrets or creating a database.
    assert not (tmp_path / "data" / "lazis.db").exists()


def test_profile_is_valid_seatbelt_syntax() -> None:
    assert shutil.which(SANDBOX_EXEC)
    out = subprocess.run(
        [SANDBOX_EXEC, "-f", str(PROFILE), "/usr/bin/true"], capture_output=True, text=True
    )
    assert out.returncode == 0, out.stderr
