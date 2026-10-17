from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest

from lazis.security import recovery
from lazis.security.recovery import RecoveryCodeError

VECTORS = Path(__file__).resolve().parents[1] / "fixtures" / "recovery_vectors.json"


def test_roundtrip_random_keys() -> None:
    for _ in range(200):
        key = secrets.token_bytes(32)
        code = recovery.encode(key)
        assert code.startswith("LZR1-")
        assert recovery.decode(code) == key


def test_shared_vectors_match_desktop_implementation() -> None:
    # The same file is checked by the Rust test suite (apps/desktop/src-tauri).
    vectors = json.loads(VECTORS.read_text())
    assert len(vectors) >= 4
    for vector in vectors:
        key = bytes.fromhex(vector["key_hex"])
        assert recovery.encode(key) == vector["code"]
        assert recovery.decode(vector["code"]) == key


def test_decoding_is_forgiving_about_formatting() -> None:
    key = secrets.token_bytes(32)
    code = recovery.encode(key)
    messy = "  " + code.lower().replace("-", " ") + "\n"
    assert recovery.decode(messy) == key
    swapped = code[:5] + code[5:].replace("0", "O").replace("1", "I")
    assert recovery.decode(swapped) == key


def test_single_symbol_typo_is_detected() -> None:
    key = secrets.token_bytes(32)
    code = recovery.encode(key)
    position = 7
    replacement = "2" if code[position] != "2" else "3"
    typo = code[:position] + replacement + code[position + 1 :]
    with pytest.raises(RecoveryCodeError):
        recovery.decode(typo)


@pytest.mark.parametrize("bad", ["", "LZR2-ABC", "LZR1-ABC", "hello world", "LZR1-" + "U" * 58])
def test_malformed_codes_are_rejected(bad: str) -> None:
    with pytest.raises(RecoveryCodeError):
        recovery.decode(bad)


def test_wrong_key_length_is_rejected() -> None:
    with pytest.raises(RecoveryCodeError):
        recovery.encode(b"short")
