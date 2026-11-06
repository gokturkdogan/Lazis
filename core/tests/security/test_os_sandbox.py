"""OS-enforced network sandbox (Seatbelt profile shared with the desktop shell).

No test here contacts anything outside this machine: "remote" probes target 192.0.2.1
(TEST-NET-1, reserved for documentation) and are refused by the kernel before a packet is
sent; the DNS probe only touches the local resolver daemon's Unix socket.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from lazis.security.network_guard import os_network_sandbox_status
from tests.conftest import REPO_ROOT
from tests.process_helpers import start_backend

PROFILE = REPO_ROOT / "apps/desktop/src-tauri/sandbox/backend.sb"
EGRESS_PROFILE = REPO_ROOT / "apps/desktop/src-tauri/sandbox/egress.sb"
STT_PROFILE = REPO_ROOT / "apps/desktop/src-tauri/sandbox/stt.sb"
SANDBOX_EXEC = "/usr/bin/sandbox-exec"
NO_SOCKET = "/dev/null/lazis-no-research-helper"  # what the shell passes without a helper
BACKEND = [SANDBOX_EXEC, "-f", str(PROFILE), "-D", f"EGRESS_SOCKET={NO_SOCKET}"]

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
        cmd = [*BACKEND, *cmd]
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
        prefix=BACKEND,
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
    out = subprocess.run([*BACKEND, "/usr/bin/true"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    egress = [SANDBOX_EXEC, "-f", str(EGRESS_PROFILE), "-D", f"EGRESS_SOCKET={NO_SOCKET}"]
    out = subprocess.run([*egress, "/usr/bin/true"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


# ----- Phase 12: the research helper's socket and profile -----------------------------------
UNIX_PROBE = r"""
import errno, json, socket, sys
def attempt(path):
    try:
        s = socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect(path); s.close()
        return "allowed"
    except OSError as exc:
        return "eperm" if exc.errno in (errno.EPERM, errno.EACCES) else "error:" + str(exc.errno)
print(json.dumps({"helper": attempt(sys.argv[1]), "other": attempt(sys.argv[2])}))
"""


def _listen(path: str) -> socket.socket:
    server = socket.socket(socket.AF_UNIX)
    server.bind(path)
    server.listen(4)
    return server


def test_the_backend_reaches_the_helper_socket_and_no_other() -> None:
    root = Path(tempfile.mkdtemp(prefix="lzs-", dir="/private/tmp"))
    try:
        helper, other = str(root / "helper.sock"), str(root / "other.sock")
        servers = [_listen(helper), _listen(other)]
        cmd = [SANDBOX_EXEC, "-f", str(PROFILE), "-D", f"EGRESS_SOCKET={helper}",
               sys.executable, "-c", UNIX_PROBE, helper, other]  # fmt: skip
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
        assert json.loads(out.stdout) == {"helper": "allowed", "other": "eperm"}
        for s in servers:
            s.close()
    finally:
        shutil.rmtree(root)


EGRESS_PROBE = rf"""
import errno, json, socket, sys
r = {{}}
def attempt(name, fn):
    try:
        fn(); r[name] = "allowed"
    except PermissionError as exc:
        r[name] = "eperm" if exc.errno in (errno.EPERM, errno.EACCES) else "guard"
    except OSError as exc:
        r[name] = "error:" + str(exc.errno)
def tcp(host, port):
    s = socket.socket(); s.settimeout(2); s.connect((host, port)); s.close()
attempt("tcp_listen", lambda: socket.socket().bind(("127.0.0.1", 0)))
attempt("loopback_other_port", lambda: tcp("127.0.0.1", int(sys.argv[2])))
attempt("ollama_port", lambda: tcp("127.0.0.1", 11434))
attempt("remote_port_80", lambda: tcp("{TEST_NET}", 80))
attempt("other_unix_socket", lambda: socket.socket(socket.AF_UNIX).connect(sys.argv[1]))
attempt("dns_daemon", lambda: socket.socket(socket.AF_UNIX).connect("/var/run/mDNSResponder"))
from lazis.providers.web import guard
guard.install()
attempt("guarded_loopback_443", lambda: tcp("127.0.0.1", 443))
attempt("guarded_private_443", lambda: tcp("10.0.0.1", 443))
attempt("guarded_bind", lambda: socket.socket().bind(("127.0.0.1", 0)))
import subprocess
attempt("guarded_process", lambda: subprocess.run(["/usr/bin/true"]))
print(json.dumps(r))
"""


def test_the_helper_profile_allows_https_and_dns_only() -> None:
    root = Path(tempfile.mkdtemp(prefix="lzs-", dir="/private/tmp"))
    try:
        mine, other = str(root / "helper.sock"), str(root / "other.sock")
        server = _listen(other)
        local = socket.socket()
        local.bind(("127.0.0.1", 0))
        local.listen(1)
        cmd = [SANDBOX_EXEC, "-f", str(EGRESS_PROFILE), "-D", f"EGRESS_SOCKET={mine}",
               sys.executable, "-c", EGRESS_PROBE, other, str(local.getsockname()[1])]  # fmt: skip
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
        r = json.loads(out.stdout.strip().splitlines()[-1])
        server.close()
        local.close()
    finally:
        shutil.rmtree(root)
    # The OS refuses every port but 443, any local service, and any other Unix socket.
    for name in ("tcp_listen", "loopback_other_port", "ollama_port", "remote_port_80",
                 "other_unix_socket"):  # fmt: skip
        assert r[name] == "eperm", (name, r[name])
    assert r["dns_daemon"] == "allowed"
    # Port 443 on a local or private address passes the OS; the helper's own guard refuses it
    # before anything is sent, as it refuses listening sockets and starting programs.
    for name in ("guarded_loopback_443", "guarded_private_443", "guarded_bind", "guarded_process"):
        assert r[name] == "guard", (name, r[name])


# ----- Phase 13: the speech-to-text server's profile -----------------------------------------
STT_PROBE = rf"""
import errno, json, socket
r = {{}}
def attempt(name, fn):
    try:
        fn(); r[name] = "allowed"
    except OSError as exc:
        r[name] = "eperm" if exc.errno in (errno.EPERM, errno.EACCES) else "error:" + str(exc.errno)
srv = socket.socket()
attempt("listen_loopback", lambda: (srv.bind(("127.0.0.1", 0)), srv.listen(1)))
def tcp(host, port):
    s = socket.socket(); s.settimeout(2); s.connect((host, port)); s.close()
attempt("ollama_port", lambda: tcp("127.0.0.1", 11434))
attempt("remote_https", lambda: tcp("{TEST_NET}", 443))
attempt("dns_daemon", lambda: socket.socket(socket.AF_UNIX).connect("/var/run/mDNSResponder"))
print(json.dumps(r))
"""


def test_the_stt_server_profile_allows_loopback_listening_only() -> None:
    out = subprocess.run([SANDBOX_EXEC, "-f", str(STT_PROFILE), sys.executable, "-c", STT_PROBE],
                         capture_output=True, text=True, timeout=60, check=True)  # fmt: skip
    r = json.loads(out.stdout.strip().splitlines()[-1])
    assert r["listen_loopback"] == "allowed"
    # Speech never leaves the machine: no outbound connection of any kind, no name resolution.
    for name in ("ollama_port", "remote_https", "dns_daemon"):
        assert r[name] == "eperm", (name, r[name])
