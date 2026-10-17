"""Start the real backend process the same way the desktop shell does (stdin secrets)."""

from __future__ import annotations

import json
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


@dataclass
class Backend:
    proc: subprocess.Popen[bytes]
    token: str
    key_hex: str
    data_dir: Path
    log_dir: Path
    handshake: dict[str, Any] = field(default_factory=dict)
    fatal: dict[str, Any] | None = None
    startup_seconds: float = 0.0

    @property
    def port(self) -> int:
        return int(self.handshake["port"])

    def get(self, path: str, token: str | None = None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token or self.token}"}
        return httpx.get(f"http://127.0.0.1:{self.port}{path}", headers=headers, timeout=5)

    def close_lifeline(self, timeout: float = 10) -> int:
        assert self.proc.stdin is not None
        self.proc.stdin.close()
        return self.proc.wait(timeout)

    def outputs(self) -> str:
        out = self.proc.stdout.read().decode() if self.proc.stdout else ""
        err = self.proc.stderr.read().decode() if self.proc.stderr else ""
        logs = "".join(p.read_text() for p in self.log_dir.glob("core.log*"))
        return out + err + logs


def start_backend(
    root: Path,
    *,
    token: str | None = None,
    key_hex: str | None = None,
    send_secrets: bool = True,
    extra_args: list[str] | None = None,
    timeout: float = 30,
    prefix: list[str] | None = None,
    pass_fds: tuple[int, ...] = (),
) -> Backend:
    token = token or secrets.token_hex(32)
    key_hex = key_hex or secrets.token_hex(32)
    data_dir, log_dir = root / "data", root / "logs"
    args = [
        *(prefix or []),
        sys.executable,
        "-I",
        "-m",
        "lazis",
        "serve",
        "--stdin-secrets",
        "--environment",
        "test",
        "--data-dir",
        str(data_dir),
        "--log-dir",
        str(log_dir),
        "--config",
        str(root / "config.toml"),
        *(extra_args or []),
    ]
    started = time.monotonic()
    proc = subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        pass_fds=pass_fds,
    )
    backend = Backend(proc, token, key_hex, data_dir, log_dir)
    assert proc.stdin is not None and proc.stdout is not None
    if send_secrets:
        line = json.dumps({"version": 1, "session_token": token, "db_key": key_hex}) + "\n"
        proc.stdin.write(line.encode())
        proc.stdin.flush()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = proc.stdout.readline()
        if not raw:
            break
        text = raw.decode().strip()
        if text.startswith("LAZIS_READY "):
            backend.handshake = json.loads(text.split(" ", 1)[1])
            break
        if text.startswith("LAZIS_FATAL "):
            backend.fatal = json.loads(text.split(" ", 1)[1])
            break
    backend.startup_seconds = time.monotonic() - started
    return backend
