"""Reading a profile file safely (Phase 8, ADR-0019).

The UI reads the file the user picked and sends its bytes; no file path crosses the API, so
the backend never opens a path the user (or a file) supplies. Here the bytes are checked —
size, encoding, binary content — decoded, normalised, and split into sections with their line
numbers. Secrets are redacted before the text goes anywhere (the model, the draft): a line
that holds a password, PIN, key, card, IBAN or id number is replaced and counted.

The content is untrusted data. Nothing here interprets it; the sections are only text.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Literal

from lazis.memory import policy

Format = Literal["markdown", "text", "json"]

MAX_FILE_BYTES = 1_000_000  # JSON up to 1 MB
MAX_TEXT_CHARS = 200_000  # Markdown/text: about 150 sections, one model call each
SECTION_CHARS = 1_400  # within the extraction's per-message limit (MAX_TARGET_CHARS 1500)
REDACTED = "[gizli bilgi çıkarıldı]"

_EXTENSIONS: dict[str, Format] = {
    ".md": "markdown", ".markdown": "markdown", ".txt": "text", ".text": "text", ".json": "json",
}  # fmt: skip


class FileRejected(ValueError):
    """``code`` is a stable reason for the UI (Turkish text lives there)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Section:
    idx: int
    heading: str  # the Markdown heading path ("Aile › Kardeşlerim"), or "" for text
    first_line: int  # 1-based line of the section's first line in the file
    body: str
    line_numbers: tuple[int, ...] = ()  # the file line of each line of ``body``


@dataclass(frozen=True)
class ReadFile:
    name: str
    format: Format
    text: str  # decoded, normalised, secrets redacted
    content_hash: str
    size_bytes: int
    redacted_lines: tuple[int, ...] = ()
    sections: tuple[Section, ...] = field(default_factory=tuple)


def format_for(name: str) -> Format:
    m = re.search(r"\.[A-Za-z]+$", name.strip())
    fmt = _EXTENSIONS.get(m.group(0).lower()) if m else None
    if fmt is None:
        raise FileRejected("unsupported_format")
    return fmt


def decode(data: bytes) -> str:
    """UTF-8 (with or without BOM) or UTF-16 with a BOM; anything else is refused, as is
    binary content (NUL characters or many control characters)."""
    if data.startswith(b"\xef\xbb\xbf"):
        raw = data[3:]
        encoding = "utf-8"
    elif data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raw, encoding = data, "utf-16"
    else:
        raw, encoding = data, "utf-8"
    try:
        out = raw.decode(encoding)
    except UnicodeDecodeError:
        raise FileRejected("encoding") from None
    if "\x00" in out:
        raise FileRejected("binary")
    controls = sum(1 for ch in out if ord(ch) < 32 and ch not in "\n\r\t\f")
    if controls > max(8, len(out) // 200):
        raise FileRejected("binary")
    return out


def _normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    return "".join(ch for ch in text if ord(ch) >= 32 or ch in "\n\t")


def redact(text: str) -> tuple[str, tuple[int, ...]]:
    """Lines with a secret are replaced (the model and the draft never see the value)."""
    out: list[str] = []
    hits: list[int] = []
    for n, line in enumerate(text.split("\n"), start=1):
        if policy.secret_kind(line):
            hits.append(n)
            out.append(REDACTED)
        else:
            out.append(line)
    return "\n".join(out), tuple(hits)


def read(name: str, data: bytes) -> ReadFile:
    if not data or not data.strip():
        raise FileRejected("empty")
    if len(data) > MAX_FILE_BYTES:
        raise FileRejected("too_large")
    fmt = format_for(name)
    text = _normalise(decode(data))
    if not text.strip():
        raise FileRejected("empty")
    if fmt != "json" and len(text) > MAX_TEXT_CHARS:
        raise FileRejected("too_long")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if fmt == "json":
        # JSON values are checked one by one later (a secret value is excluded there).
        return ReadFile(_safe_name(name), fmt, text, digest, len(data))
    clean, hits = redact(text)
    sections = markdown_sections(clean) if fmt == "markdown" else text_sections(clean)
    return ReadFile(_safe_name(name), fmt, clean, digest, len(data), hits, tuple(sections))


def _safe_name(name: str) -> str:
    """Only the base name is kept (for the user's history); never used as a path."""
    base = re.split(r"[\\/]", name.strip())[-1]
    return base[:120] or "profil"


# ----- sections -------------------------------------------------------------------------
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
Line = tuple[int, str]  # (file line number, text)


def _lines(text: str) -> list[Line]:
    """Lines with over-long ones cut into pieces (the pieces keep the line number)."""
    out: list[Line] = []
    for n, line in enumerate(text.split("\n"), start=1):
        while len(line) > SECTION_CHARS:
            cut = line.rfind(" ", 0, SECTION_CHARS)
            cut = cut if cut > SECTION_CHARS // 2 else SECTION_CHARS
            out.append((n, line[:cut]))
            line = line[cut:].lstrip()
        out.append((n, line))
    return out


def _paragraphs(lines: list[Line]) -> list[list[Line]]:
    paras: list[list[Line]] = []
    cur: list[Line] = []
    for n, line in lines:
        if not line.strip():
            if cur:
                paras.append(cur)
                cur = []
            continue
        cur.append((n, line.rstrip()))
    if cur:
        paras.append(cur)
    return paras


def _pack(paras: list[list[Line]], heading: str, start_idx: int) -> list[Section]:
    """Paragraphs packed into sections of at most SECTION_CHARS (a longer paragraph is split
    between its lines). Each section keeps the file line of every line it holds."""
    out: list[Section] = []
    cur: list[Line] = []
    size = 0

    def close() -> None:
        nonlocal cur, size
        if cur:
            out.append(Section(start_idx + len(out), heading, cur[0][0],
                               "\n".join(t for _, t in cur), tuple(n for n, _ in cur)))  # fmt: skip
        cur, size = [], 0

    for para in paras:
        para_size = sum(len(t) + 1 for _, t in para)
        if cur and size + para_size > SECTION_CHARS:
            close()
        for n, t in para:
            if cur and size + len(t) + 1 > SECTION_CHARS:
                close()
            cur.append((n, t))
            size += len(t) + 1
    close()
    return out


def text_sections(text: str) -> list[Section]:
    return _pack(_paragraphs(_lines(text)), "", 0)


def markdown_sections(text: str) -> list[Section]:
    """Cut at headings; the heading path names the section ("Aile › Kardeşlerim"). The
    heading line itself stays in the section text (it is context for the reader)."""
    out: list[Section] = []
    path: list[str] = []
    current: list[Line] = []

    def flush() -> None:
        if any(line.strip() and not _HEADING.match(line) for _, line in current):
            out.extend(_pack(_paragraphs(current), " › ".join(path), len(out)))
        current.clear()

    for n, line in _lines(text):
        m = _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            path[:] = [*path[: level - 1], m.group(2).strip()[:80]]
        current.append((n, line))
    flush()
    return out


def line_of(section: Section, excerpt: str) -> int | None:
    """The file line where a quoted excerpt is (None if it is not in the section)."""
    if not excerpt:
        return None
    from lazis.memory import extraction

    for n, line in zip(section.line_numbers, section.body.split("\n"), strict=False):
        if extraction.quote_in(excerpt, line):
            return n
    return section.first_line if extraction.quote_in(excerpt, section.body) else None


def line_text(section: Section, excerpt: str) -> str:
    """The whole line a quoted excerpt is on (for words around the quote), or ""."""
    if not excerpt:
        return ""
    from lazis.memory import extraction

    for line in section.body.split("\n"):
        if extraction.quote_in(excerpt, line):
            return line
    return ""
