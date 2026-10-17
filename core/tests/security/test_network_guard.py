"""The audit-hook network guard runs in a subprocess (hooks cannot be uninstalled)."""

from __future__ import annotations

import json
import subprocess
import sys

from lazis.security.network_guard import is_loopback_host

PROBE = r"""
import json, socket, tempfile, os
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
srv = socket.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
port = srv.getsockname()[1]
attempt("loopback_connect", lambda: socket.create_connection(("127.0.0.1", port), timeout=1).close())
attempt("remote_connect_ip", lambda: socket.socket().connect(("1.1.1.1", 443)))
attempt("remote_connect_name", lambda: socket.create_connection(("example.com", 443), timeout=1))
attempt("dns_lookup", lambda: socket.getaddrinfo("example.com", 443))
attempt("wildcard_bind", lambda: socket.socket().bind(("0.0.0.0", 0)))
attempt("udp_sendto", lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b"x", ("8.8.8.8", 53)))
path = os.path.join(tempfile.mkdtemp(), "s.sock")
u = socket.socket(socket.AF_UNIX); u.bind(path); u.listen(1)
attempt("unix_socket", lambda: socket.socket(socket.AF_UNIX).connect(path))
import urllib.request
attempt("urllib_https", lambda: urllib.request.urlopen("https://example.com", timeout=1))
print(json.dumps(results))
"""


def test_guard_blocks_everything_but_loopback_and_unix_sockets() -> None:
    out = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, check=True, timeout=30
    )
    results = json.loads(out.stdout.strip().splitlines()[-1])
    assert results["loopback_connect"] == "allowed"
    assert results["unix_socket"] == "allowed"
    for name in (
        "remote_connect_ip",
        "remote_connect_name",
        "dns_lookup",
        "wildcard_bind",
        "udp_sendto",
    ):
        assert results[name] == "blocked", name
    # urllib wraps the PermissionError in URLError (an OSError subclass)
    assert results["urllib_https"] != "allowed"


def test_loopback_detection() -> None:
    assert is_loopback_host("127.0.0.1") and is_loopback_host("::1")
    assert is_loopback_host("127.5.6.7") and is_loopback_host("localhost")
    for host in ("", "0.0.0.0", "10.0.0.1", "example.com", None, "::"):
        assert not is_loopback_host(host)
