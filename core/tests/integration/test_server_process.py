"""The real managed backend process: startup, shutdown, restart, failure modes, hygiene."""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from tests.process_helpers import start_backend

pytestmark = pytest.mark.slow


def _listening_addresses(pid: int) -> list[str]:
    out = subprocess.run(
        ["lsof", "-nP", "-a", "-p", str(pid), "-iTCP", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [line.split()[8] for line in out.splitlines()[1:] if len(line.split()) > 8]


def _non_loopback_ipv4() -> str | None:
    try:
        out = subprocess.run(
            ["ipconfig", "getifaddr", "en0"], capture_output=True, text=True, check=False, timeout=5
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out or None


def test_start_serve_and_graceful_shutdown(tmp_path: Path) -> None:
    backend = start_backend(tmp_path)
    try:
        assert backend.fatal is None, backend.fatal
        assert backend.handshake["api_version"] == "v1"
        assert backend.get("/api/v1/health").json()["status"] == "ok"
        status = backend.get("/api/v1/system/status").json()
        assert status["database"]["encryption_verified"] is True
        assert status["backend"]["pid"] == backend.proc.pid
    finally:
        code = backend.close_lifeline()
    assert code == 0
    logs = backend.outputs()
    assert '"app.stopping", "reason": "lifeline_closed"' in logs
    assert '"app.stopped"' in logs


def test_binds_to_loopback_only(tmp_path: Path) -> None:
    backend = start_backend(tmp_path)
    try:
        addresses = _listening_addresses(backend.proc.pid)
        assert addresses == [f"127.0.0.1:{backend.port}"], addresses
        lan_ip = _non_loopback_ipv4()
        if lan_ip:
            with pytest.raises(OSError):
                socket.create_connection((lan_ip, backend.port), timeout=2)
    finally:
        backend.close_lifeline()


def test_unauthenticated_and_foreign_requests_are_rejected(tmp_path: Path) -> None:
    backend = start_backend(tmp_path)
    try:
        base = f"http://127.0.0.1:{backend.port}/api/v1/health"
        assert httpx.get(base, timeout=5).status_code == 401
        assert backend.get("/api/v1/health", token="0" * 64).status_code == 401
        evil = httpx.get(
            base,
            headers={"Authorization": f"Bearer {backend.token}", "Origin": "https://evil.example"},
            timeout=5,
        )
        assert evil.status_code == 403
    finally:
        backend.close_lifeline()


def test_restart_preserves_encrypted_data_and_identity(tmp_path: Path) -> None:
    first = start_backend(tmp_path)
    instance = first.get("/api/v1/system/status").json()["database"]["instance_id"]
    assert first.close_lifeline() == 0
    second = start_backend(tmp_path, key_hex=first.key_hex)
    try:
        assert second.fatal is None
        assert second.get("/api/v1/system/status").json()["database"]["instance_id"] == instance
    finally:
        second.close_lifeline()


def test_wrong_key_fails_closed_with_code(tmp_path: Path) -> None:
    start_backend(tmp_path).close_lifeline()
    wrong = start_backend(tmp_path)  # new random key
    assert wrong.fatal is not None and wrong.fatal["code"] == "database_key_invalid"
    assert wrong.proc.wait(10) == 3


def test_second_instance_on_same_data_dir_is_refused(tmp_path: Path) -> None:
    first = start_backend(tmp_path)
    try:
        second = start_backend(tmp_path, key_hex=first.key_hex)
        assert second.fatal is not None and second.fatal["code"] == "instance_already_running"
        assert second.proc.wait(10) == 3
        assert first.get("/api/v1/health").status_code == 200
    finally:
        first.close_lifeline()


def test_missing_secrets_time_out(tmp_path: Path) -> None:
    backend = start_backend(tmp_path, send_secrets=False, extra_args=["--secrets-timeout", "1"])
    assert backend.fatal is not None and backend.fatal["code"] == "secrets_missing"
    assert backend.proc.wait(10) == 3
    assert not (tmp_path / "data" / "lazis.db").exists()  # nothing created without a key


def test_invalid_config_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('[backend]\nhost = "0.0.0.0"\n')
    backend = start_backend(tmp_path)
    assert backend.fatal is not None and backend.fatal["code"] == "config_invalid"
    assert backend.proc.wait(10) == 3


def test_sigterm_is_graceful(tmp_path: Path) -> None:
    backend = start_backend(tmp_path)
    os.kill(backend.proc.pid, signal.SIGTERM)
    assert backend.proc.wait(10) == 0
    logs = backend.outputs()
    assert '"reason": "signal_SIGTERM"' in logs
    assert '"storage.closed"' in logs and '"app.stopped"' in logs


def test_secrets_never_reach_stdout_stderr_or_logs(tmp_path: Path) -> None:
    backend = start_backend(tmp_path)
    backend.get("/api/v1/health")
    backend.get("/api/v1/health", token="f" * 64)  # a denied request is logged too
    backend.close_lifeline()
    everything = backend.outputs()
    assert backend.token not in everything
    assert backend.key_hex not in everything
    assert backend.key_hex.upper() not in everything


def test_startup_time_is_reasonable(tmp_path: Path) -> None:
    backend = start_backend(tmp_path)
    try:
        assert backend.startup_seconds < 10, backend.startup_seconds
    finally:
        backend.close_lifeline()


def test_backend_exits_when_parent_holding_the_lifeline_dies(tmp_path: Path) -> None:
    """Orphan prevention: the shell crashing closes the pipe, so the backend shuts down."""
    backend = start_backend(tmp_path)
    pid = backend.proc.pid
    assert backend.proc.stdin is not None
    backend.proc.stdin.close()  # what the OS does when the parent dies
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and backend.proc.poll() is None:
        time.sleep(0.1)
    assert backend.proc.poll() == 0, f"backend {pid} still running"
