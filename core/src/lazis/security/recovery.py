"""Recovery-code codec (format ``LZR1``), byte-for-byte compatible with the desktop shell.

The recovery code *is* the 256-bit database key, encoded for humans, plus a checksum that
catches typos. Whoever holds it can decrypt the data — there is no other backdoor.

    payload = key (32 bytes) || SHA-256("LAZIS-RECOVERY-v1" || key)[:4]
    code    = "LZR1-" + Crockford-base32(payload) in groups of 5   (58 symbols)

Decoding is forgiving: case-insensitive, ignores spaces and hyphens, maps O→0 and I/L→1.
"""

from __future__ import annotations

import hashlib

PREFIX = "LZR1"
CHECK_CONTEXT = b"LAZIS-RECOVERY-v1"
KEY_BYTES = 32
CHECK_BYTES = 4
GROUP = 5
_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_DECODE = {c: i for i, c in enumerate(_ALPHABET)}
_ALIASES = {"O": "0", "I": "1", "L": "1"}
_SYMBOLS = ((KEY_BYTES + CHECK_BYTES) * 8 + 4) // 5  # 58


class RecoveryCodeError(ValueError):
    pass


def _checksum(key: bytes) -> bytes:
    return hashlib.sha256(CHECK_CONTEXT + key).digest()[:CHECK_BYTES]


def _b32encode(data: bytes) -> str:
    value = int.from_bytes(data, "big")
    bits = len(data) * 8
    pad = (-bits) % 5
    value <<= pad
    symbols = (bits + pad) // 5
    return "".join(_ALPHABET[(value >> (5 * (symbols - 1 - i))) & 0x1F] for i in range(symbols))


def _b32decode(text: str, nbytes: int) -> bytes:
    value = 0
    for char in text:
        try:
            value = (value << 5) | _DECODE[char]
        except KeyError:
            raise RecoveryCodeError("invalid character in recovery code") from None
    pad = len(text) * 5 - nbytes * 8
    if pad < 0 or pad >= 5 or value & ((1 << pad) - 1):
        raise RecoveryCodeError("recovery code has the wrong length")
    return (value >> pad).to_bytes(nbytes, "big")


def encode(key: bytes) -> str:
    if len(key) != KEY_BYTES:
        raise RecoveryCodeError("key must be 32 bytes")
    body = _b32encode(key + _checksum(key))
    groups = [body[i : i + GROUP] for i in range(0, len(body), GROUP)]
    return "-".join([PREFIX, *groups])


def _strip(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch not in " -\t\r\n")


def decode(code: str) -> bytes:
    cleaned = _strip(code)
    if not cleaned.startswith(PREFIX):
        raise RecoveryCodeError("recovery code must start with LZR1")
    # Aliases apply to the payload only (the prefix itself contains an 'L').
    body = "".join(_ALIASES.get(ch, ch) for ch in cleaned[len(PREFIX) :])
    if len(body) != _SYMBOLS:
        raise RecoveryCodeError("recovery code has the wrong length")
    payload = _b32decode(body, KEY_BYTES + CHECK_BYTES)
    key, check = payload[:KEY_BYTES], payload[KEY_BYTES:]
    if _checksum(key) != check:
        raise RecoveryCodeError("recovery code checksum mismatch (typo?)")
    return key
