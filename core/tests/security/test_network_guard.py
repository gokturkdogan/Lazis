"""The application-level guard (audit hook) runs in a subprocess (hooks cannot be uninstalled).

Nothing here contacts another host: the guard refuses before any packet or DNS query is sent,
and the targets are TEST-NET-1 (192.0.2.1) and the reserved ``.invalid`` TLD anyway.
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

from lazis.security.network_guard import is_loopback_host, is_loopback_ip
from tests.process_helpers import start_backend

PROBE = r"""
import json, os, socket, subprocess, tempfile
from lazis.security.network_guard import install_network_guard
install_network_guard()
results = {}
def attempt(name, fn):
    try:
        fn(); results[name] = "allowed"
    except PermissionError:
        results[name] = "blocked"
    except OSError as exc:
        results[name] = "oserror:" + type(exc).__name__
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(5)
port = srv.getsockname()[1]
srv6 = socket.socket(socket.AF_INET6); srv6.bind(("::1", 0)); srv6.listen(5)
port6 = srv6.getsockname()[1]
attempt("loopback_connect", lambda: socket.create_connection(("127.0.0.1", port), timeout=1).close())
attempt("loopback_ipv6_connect", lambda: socket.create_connection(("::1", port6), timeout=1).close())
attempt("localhost_resolved_then_connect", lambda: socket.create_connection(("localhost", port), timeout=1).close())
attempt("raw_connect_by_name", lambda: socket.socket().connect(("localhost", port)))
attempt("remote_connect_ip", lambda: socket.socket().connect(("192.0.2.1", 9)))
attempt("remote_connect_ex", lambda: socket.socket().connect_ex(("192.0.2.1", 9)))
attempt("remote_connect_ipv6", lambda: socket.socket(socket.AF_INET6).connect(("2001:db8::1", 9)))
attempt("remote_connect_name", lambda: socket.create_connection(("lazis-test.invalid", 9), timeout=1))
attempt("dns_getaddrinfo", lambda: socket.getaddrinfo("lazis-test.invalid", 9))
attempt("dns_gethostbyname", lambda: socket.gethostbyname("lazis-test.invalid"))
attempt("dns_gethostbyname_ex", lambda: socket.gethostbyname_ex("lazis-test.invalid"))
attempt("wildcard_bind", lambda: socket.socket().bind(("0.0.0.0", 0)))
attempt("wildcard_bind_ipv6", lambda: socket.socket(socket.AF_INET6).bind(("::", 0)))
attempt("empty_host_bind", lambda: socket.socket().bind(("", 0)))
attempt("udp_sendto", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("192.0.2.1", 9)))
attempt("udp_sendmsg", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendmsg([b"x"], [], 0, ("192.0.2.1", 9)))
path = os.path.join(tempfile.mkdtemp(), "s.sock")
u = socket.socket(socket.AF_UNIX); u.bind(path); u.listen(1)
attempt("unix_socket", lambda: socket.socket(socket.AF_UNIX).connect(path))
import urllib.request
attempt("urllib_http", lambda: urllib.request.urlopen("http://192.0.2.1:9/", timeout=1))
attempt("subprocess_run", lambda: subprocess.run(["/usr/bin/true"], check=True))
attempt("os_system", lambda: os.system("/usr/bin/true"))
attempt("os_posix_spawn", lambda: os.posix_spawn("/usr/bin/true", ["true"], dict(os.environ)))
attempt("os_execv", lambda: os.execv("/usr/bin/true", ["true"]))
attempt("os_fork", lambda: os.fork())
print(json.dumps(results))
"""


def test_guard_blocks_everything_but_loopback_and_unix_sockets() -> None:
    out = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True, timeout=30
    )
    results = json.loads(out.stdout.strip().splitlines()[-1])
    for name in (
        "loopback_connect",
        "loopback_ipv6_connect",
        "localhost_resolved_then_connect",  # getaddrinfo("localhost") → connect to an IP
        "unix_socket",
    ):
        assert results[name] == "allowed", name
    for name in (
        "raw_connect_by_name",  # names are resolved inside connect() without an audit event
        "remote_connect_ip",
        "remote_connect_ex",
        "remote_connect_ipv6",
        "remote_connect_name",
        "dns_getaddrinfo",
        "dns_gethostbyname",
        "dns_gethostbyname_ex",
        "wildcard_bind",
        "wildcard_bind_ipv6",
        "empty_host_bind",
        "udp_sendto",
        "udp_sendmsg",
        "subprocess_run",
        "os_system",
        "os_posix_spawn",
        "os_execv",
        "os_fork",
    ):
        assert results[name] == "blocked", (name, results[name])
    # urllib wraps the PermissionError in URLError (an OSError subclass)
    assert results["urllib_http"] != "allowed"


def test_loopback_detection() -> None:
    assert is_loopback_host("127.0.0.1") and is_loopback_host("::1")
    assert is_loopback_host("127.5.6.7") and is_loopback_host("localhost")
    for host in ("", "0.0.0.0", "10.0.0.1", "example.com", None, "::", 0):
        assert not is_loopback_host(host)
    # Socket-level checks accept IP literals only.
    assert not is_loopback_ip("localhost")
    assert is_loopback_ip("::1%lo0")
    assert is_loopback_ip("::ffff:127.0.0.1")
    assert not is_loopback_ip("::ffff:192.0.2.1")
    assert not is_loopback_ip("fe80::1%lo0")
    assert not is_loopback_ip("127.0.0.1.lazis-test.invalid")


def test_backend_closes_inherited_descriptors(tmp_path: Path) -> None:
    """A socket leaked by the parent must not stay usable inside the backend."""
    leaked = socket.socket()
    leaked.bind(("127.0.0.1", 0))
    leaked.listen(1)
    leaked_port = leaked.getsockname()[1]
    backend = start_backend(tmp_path, pass_fds=(leaked.fileno(),))
    try:
        assert backend.fatal is None, backend.outputs()
        lsof = subprocess.run(
            ["/usr/sbin/lsof", "-nP", "-a", "-p", str(backend.proc.pid), f"-iTCP:{leaked_port}"],
            capture_output=True,
            text=True,
        )
        assert lsof.stdout.strip() == "", lsof.stdout
        assert backend.close_lifeline() == 0
        log = (backend.log_dir / "core.log").read_text()
        starting = next(json.loads(line) for line in log.splitlines() if "app.starting" in line)
        assert starting["inherited_descriptors_closed"] >= 1
        assert "socket" in starting["inherited_descriptor_kinds"]
    finally:
        leaked.close()
        if backend.proc.poll() is None:
            backend.proc.kill()
