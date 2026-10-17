"""Application-level network and process guard (PEP 578 audit hook).

What it is — and is not:

* It sees only operations that go through CPython's own modules: ``socket`` (connect,
  sendto, sendmsg, bind, DNS helpers) and process creation (``subprocess``, ``os.system``,
  ``os.exec*``, ``os.posix_spawn*``, ``os.spawn*``, ``os.fork*``). Every such operation to a
  non-loopback destination, and every attempt to start another program, is refused *before*
  it happens. Loopback IP literals and Unix domain sockets stay allowed.
* It does **not** see native code (C extensions, ``ctypes``, a Rust/C HTTP client inside a
  wheel) that calls the OS directly, nor already-connected sockets inherited from the parent.
  Those are covered by two other layers: the desktop shell runs the backend under an
  OS-enforced sandbox profile that denies outbound network access to other hosts
  (:func:`os_network_sandbox_status` verifies it), and inherited descriptors are closed at
  startup (:func:`close_inherited_descriptors`).

Audit hooks cannot be removed once installed, which is exactly the property we want.
"""

from __future__ import annotations

import contextlib
import errno
import ipaddress
import os
import socket
import stat
import sys
from collections.abc import Callable
from typing import Any, Literal

from lazis.errors import NetworkBlockedError

_LOOPBACK_NAMES = frozenset({"localhost", "localhost.", "ip6-localhost"})
_SOCKET_ADDRESS_EVENTS = frozenset(
    {"socket.connect", "socket.sendto", "socket.sendmsg", "socket.bind"}
)
_DNS_EVENTS = frozenset({"socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo"})
# The backend has no reason to start other programs in P1–P12 (P13 adds an allowlisted audio
# helper). Under the OS sandbox a child would inherit the network restrictions anyway; this
# keeps a compromised dependency from running tools at all.
_PROCESS_EVENTS = frozenset(
    {
        "subprocess.Popen",
        "os.system",
        "os.exec",
        "os.posix_spawn",
        "os.spawn",
        "os.fork",
        "os.forkpty",
    }
)
# The local DNS daemon. Connecting to it sends nothing off the machine; the sandbox profile
# denies it, so it doubles as a harmless probe for "is the OS sandbox enforced?".
_DNS_DAEMON_SOCKET = "/var/run/mDNSResponder"

SandboxStatus = Literal["enforced", "not_enforced", "unknown"]

_installed = False
_on_block: Callable[[str, str], None] | None = None


def is_loopback_host(host: object) -> bool:
    """Loopback IP literal or a well-known loopback *name* (used for DNS-level checks)."""
    if isinstance(host, str) and host.lower() in _LOOPBACK_NAMES:
        return True
    return is_loopback_ip(host)


def is_loopback_ip(host: object) -> bool:
    """True only for loopback IP *literals* (IPv4, IPv6, IPv4-mapped IPv6, with scope)."""
    if not isinstance(host, str) or not host:
        return False
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped.is_loopback
    return address.is_loopback


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
    raise NetworkBlockedError(f"blocked by policy ({event})")


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if event in _PROCESS_EVENTS:
        _block(event, "process")
    if not event.startswith("socket."):
        return
    if event in _SOCKET_ADDRESS_EVENTS:
        sock, address = args[0], args[1] if len(args) > 1 else None
        family = getattr(sock, "family", None)
        if family == socket.AF_UNIX or address is None:
            return
        host = _address_host(address)
        # Socket addresses must be loopback IP *literals*: a name such as "localhost" would be
        # resolved inside the call without another audit event, so it could not be checked.
        if not is_loopback_ip(host):
            _block(event, host if host in ("", "0.0.0.0", "::") else "non-loopback")  # noqa: S104
    elif event == "socket.getaddrinfo":
        host = args[0] if args else None
        if host is None:
            return
        if isinstance(host, bytes):
            host = host.decode("ascii", "replace")
        if not is_loopback_host(host):
            _block(event, "name")
    elif event in _DNS_EVENTS:
        host = _address_host(args[0]) if args else None
        if not is_loopback_host(host):
            _block(event, "name")


def install_network_guard(on_block: Callable[[str, str], None] | None = None) -> None:
    """Install the guard once per process. Idempotent."""
    global _installed, _on_block
    _on_block = on_block
    if not _installed:
        sys.addaudithook(_hook)
        _installed = True


def guard_installed() -> bool:
    return _installed


def os_network_sandbox_status(dns_socket: str = _DNS_DAEMON_SOCKET) -> SandboxStatus:
    """Whether the OS (not this process) denies network access, probed without leaving the
    machine: a connect to the local DNS daemon's Unix socket is refused (EPERM) only when
    the sandbox profile is active. AF_UNIX is allowed by the audit hook, so the answer comes
    from the kernel."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(2)
        probe.connect(dns_socket)
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.EACCES):
            return "enforced"
        return "unknown"
    else:
        return "not_enforced"
    finally:
        probe.close()


def _descriptor_kind(fd: int) -> str:
    mode = os.fstat(fd).st_mode
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISFIFO(mode):
        return "pipe"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISCHR(mode):
        return "device"
    return "other"


def close_inherited_descriptors(keep: frozenset[int] = frozenset({0, 1, 2})) -> list[str]:
    """Close file descriptors inherited from the parent (anything inheritable beyond stdio).

    CPython creates non-inheritable descriptors (PEP 446), so an *inheritable* descriptor at
    startup can only have come from the parent. An inherited, already-connected socket would
    bypass both the audit hook (no connect event) and the sandbox's connect-time check.
    Returns the kinds of the descriptors closed (for the log; never their targets).
    """
    closed: list[str] = []
    for name in os.listdir("/dev/fd"):
        fd = int(name)
        if fd in keep:
            continue
        try:
            if os.get_inheritable(fd):
                kind = _descriptor_kind(fd)
                os.close(fd)
                closed.append(kind)
        except OSError:
            continue  # already gone (e.g. the descriptor listdir itself used)
    return sorted(closed)
