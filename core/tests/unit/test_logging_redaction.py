from __future__ import annotations

import json
import logging
import secrets
import stat
from pathlib import Path

from lazis.config.model import LoggingSection
from lazis.observability import SecretRegistry, get_logger, log_event, setup_logging
from lazis.observability.redaction import REDACTED


def test_registry_scrubs_registered_secrets_and_patterns() -> None:
    reg = SecretRegistry()
    token = secrets.token_hex(32)
    reg.register(token)
    text = (
        f"token={token} auth=Bearer abc.def-123 key=x'{'ab' * 32}' "
        "code=LZR1-ABCDE-FGHJK-MNPQR-STVWX-YZ012-34567-89ABC"
    )
    out = reg.scrub(text)
    assert token not in out
    assert "Bearer abc" not in out
    assert "ab" * 32 not in out
    assert "LZR1-ABCDE" not in out
    assert out.count(REDACTED) >= 4


def test_short_values_are_not_registered() -> None:
    reg = SecretRegistry()
    reg.register("abc")
    assert reg.scrub("abc") == "abc"


def _read_lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_json_logs_are_redacted_private_and_structured(tmp_path: Path) -> None:
    reg = SecretRegistry()
    secret = secrets.token_hex(32)
    reg.register(secret)
    handler = setup_logging(LoggingSection(directory=tmp_path / "logs"), reg)
    log = get_logger("test")
    log.info("plain message with %s", secret)
    log_event(log, logging.INFO, "event.with_fields", leaked=secret, nested={"k": [secret]}, n=3)
    try:
        raise RuntimeError(f"boom {secret}")
    except RuntimeError as exc:
        log.error("event.failure", exc_info=exc)
    handler.flush()

    log_file = tmp_path / "logs" / "core.log"
    raw = log_file.read_text()
    assert secret not in raw
    lines = _read_lines(log_file)
    assert [line["event"] for line in lines][-2:] == ["event.with_fields", "event.failure"]
    assert lines[-2]["n"] == 3
    assert "RuntimeError" in str(lines[-1]["exception"])
    assert stat.S_IMODE(log_file.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "logs").stat().st_mode) == 0o700


def test_rotation_is_bounded(tmp_path: Path) -> None:
    handler = setup_logging(
        LoggingSection(directory=tmp_path / "logs", max_bytes=64 * 1024, backup_count=2),
        SecretRegistry(),
    )
    log = get_logger("rotation")
    for i in range(3000):
        log_event(log, logging.INFO, "filler", i=i, pad="x" * 100)
    handler.flush()
    files = sorted(p.name for p in (tmp_path / "logs").iterdir())
    assert files == ["core.log", "core.log.1", "core.log.2"]
