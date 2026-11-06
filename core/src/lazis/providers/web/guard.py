"""What the research helper may connect to (Phase 12).

Two checks, both in the helper process:

* :func:`check_url` before a request (and again for every redirect): HTTPS only, port 443, no
  user name or password in the URL, a host name (never an IP literal), not ``localhost`` or a
  local name, and on the allowlist. ``file:``, ``http:``, ``ftp:`` and the rest are refused.
* :func:`install` adds an audit hook that checks the **address actually connected to**, after
  DNS: a public (global) address on port 443, or the helper's own Unix socket. Private, loopback,
  link-local, multicast and reserved ranges are refused at connect time, which also defeats DNS
  rebinding (a name that resolves to a private address). The helper starts no programs.

The OS profile (``sandbox/egress.sb``) allows outbound TCP to port 443 only; it cannot tell
public from private addresses, which is why the hook exists.
"""

from __future__ import annotations

import ipaddress
import socket
import sys
from typing import Any
from urllib.parse import urlsplit

ALLOWED_HOSTS: frozenset[str] = frozenset({"tr.wikipedia.org", "en.wikipedia.org"})
MAX_URL = 2048
_LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".arpa")
_PROCESS_EVENTS = frozenset(
    {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork",
     "os.forkpty"}
)  # fmt: skip


class EgressRefused(Exception):
    """A request or connection the rules do not allow. ``code`` is safe to show and log."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def check_url(url: str, hosts: frozenset[str] = ALLOWED_HOSTS) -> str:
    """The URL, if it may be fetched; else :class:`EgressRefused` with the reason."""
    if len(url) > MAX_URL:
        raise EgressRefused("url_too_long")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise EgressRefused("url_invalid") from None
    if parts.scheme != "https":
        raise EgressRefused("url_scheme")
    if parts.username is not None or parts.password is not None:
        raise EgressRefused("url_credentials")
    if port not in (None, 443):
        raise EgressRefused("url_port")
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise EgressRefused("url_invalid")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise EgressRefused("url_ip_literal")
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES) or "." not in host:
        raise EgressRefused("url_local")
    if host not in hosts:
        raise EgressRefused("url_host_not_allowed")
    return url


def address_allowed(ip: str, port: int) -> bool:
    """A public address on port 443 (IPv4, IPv6 or IPv4-mapped IPv6)."""
    if port != 443:
        return False
    try:
        address = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if event in _PROCESS_EVENTS:
        raise PermissionError("the research helper starts no programs")
    if event not in ("socket.connect", "socket.sendto", "socket.sendmsg", "socket.bind"):
        return
    sock = args[0]
    family = getattr(sock, "family", None)
    if family == socket.AF_UNIX:
        return
    if event == "socket.bind":
        raise PermissionError("the research helper listens on its Unix socket only")
    address = args[1] if len(args) > 1 else None
    if event == "socket.sendmsg" or not isinstance(address, tuple) or len(address) < 2:  # pyright: ignore[reportUnknownArgumentType]
        raise PermissionError("refused connection")
    if not address_allowed(str(address[0]), int(address[1])):  # pyright: ignore[reportUnknownArgumentType]
        raise PermissionError("refused connection: not a public address on port 443")


_installed = False


def install() -> None:
    """Add the connection check to this process (once; audit hooks cannot be removed)."""
    global _installed
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True
