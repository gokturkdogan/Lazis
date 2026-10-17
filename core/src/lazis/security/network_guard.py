"""Process-wide network guard (PEP 578 audit hook).

While outbound network access is disabled (all of Phase 1), every non-loopback network
operation in this Python process is refused *before* it happens: connections, datagrams,
binds to non-loopback interfaces and DNS lookups of non-loopback names. Loopback and Unix
domain sockets stay allowed (the local API, local inference later).

Audit hooks cannot be removed once installed, which is exactly the property we want.
"""

from __future__ import annotations

import contextlib
import ipaddress
import socket
import sys
from collections.abc import Callable
from typing import Any

from lazis.errors import NetworkBlockedError

_LOOPBACK_NAMES = frozenset({"localhost", "localhost.", "ip6-localhost"})
_installed = False
_on_block: Callable[[str, str], None] | None = None


def is_loopback_host(host: object) -> bool:
    if not isinstance(host, str) or not host:
        return False
    if host.lower() in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _address_host(address: Any) -> object:
    if isinstance(address, tuple):
        items: tuple[object, ...] = address  # pyright: ignore[reportUnknownVariableType]
        return items[0] if items else None
    return address


def _block(event: str, host: object) -> None:
    target = host if isinstance(host, str) else type(host).__name__
    if _on_block is not None:
        with contextlib.suppress(Exception):  # reporting must never break enforcement
            _on_block(event, target)
    raise NetworkBlockedError(f"network access blocked ({event})")


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if not event.startswith("socket."):
        return
    if event in ("socket.connect", "socket.sendto", "socket.sendmsg", "socket.bind"):
        sock, address = args[0], args[1] if len(args) > 1 else None
        family = getattr(sock, "family", None)
        if family == socket.AF_UNIX or address is None:
            return
        host = _address_host(address)
        if event == "socket.bind" and host in ("", "0.0.0.0", "::"):  # noqa: S104 - checking, not binding
            _block(event, "wildcard")
        if not is_loopback_host(host):
            _block(event, host)
    elif event == "socket.getaddrinfo":
        host = args[0] if args else None
        if host is None:
            return
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if not is_loopback_host(host):
            _block(event, host)
    elif event in ("socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo"):
        host = _address_host(args[0]) if args else None
        if not is_loopback_host(host):
            _block(event, host)


def install_network_guard(on_block: Callable[[str, str], None] | None = None) -> None:
    """Install the guard once per process. Idempotent."""
    global _installed, _on_block
    _on_block = on_block
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True


def guard_installed() -> bool:
    return _installed
