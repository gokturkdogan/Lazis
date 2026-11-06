"""Text out of a document the user chose (Phase 11, first version): TXT, PDF text layer, DOCX.

The bytes come from a file the user picked in the app; nothing here opens a path. Parsing runs in
the backend process: the process guard allows no worker process before P13, so the limits below
keep a hostile or broken file from taking the backend with it — size, pages, characters, the
DOCX's unpacked size, no DTD in its XML, and a time limit checked between PDF pages. pypdf is
pure Python (no native parser), so a bad file can cost time, not memory safety.

What is refused carries a reason (``document_<reason>``) and never any of the file's content.
OCR is out of scope: a scanned PDF without a text layer is refused as ``no_text``.
"""

from __future__ import annotations

import io
import re
import time
import zipfile
from dataclasses import dataclass
from typing import Literal
from xml.etree import ElementTree

from lazis.errors import DocumentRefusedError

Kind = Literal["txt", "pdf", "docx"]

MAX_BYTES = 10_000_000
MAX_PAGES = 500
MAX_CHARS = 1_000_000
MAX_SECONDS = 20.0
MAX_DOCX_XML = 30_000_000

_EXTENSIONS: dict[str, Kind] = {".txt": "txt", ".pdf": "pdf", ".docx": "docx"}
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_BLANK_LINES = re.compile(r"\n{3,}")
_SPACES = re.compile(r"[ \t]+\n")


@dataclass(frozen=True)
class Section:
    """A page of a PDF, or the whole text of a TXT or DOCX."""

    page: int | None
    text: str


@dataclass(frozen=True)
class Extracted:
    kind: Kind
    sections: tuple[Section, ...]
    pages: int | None  # PDF only
    truncated: bool  # the page, character or time limit cut it short

    @property
    def chars(self) -> int:
        return sum(len(s.text) for s in self.sections)


def kind_of(name: str) -> Kind:
    dot = name.rfind(".")
    kind = _EXTENSIONS.get(name[dot:].lower()) if dot >= 0 else None
    if kind is None:
        raise DocumentRefusedError("unsupported")
    return kind


def extract(name: str, data: bytes) -> Extracted:
    """The text of one document. Raises :class:`DocumentRefusedError` with the reason."""
    kind = kind_of(name)
    if len(data) > MAX_BYTES:
        raise DocumentRefusedError("too_large", status=413)
    if not data:
        raise DocumentRefusedError("empty")
    if kind == "pdf":
        result = _pdf(data)
    elif kind == "docx":
        result = _docx(data)
    else:
        text, cut = _limit(clean(_decode(data)))
        result = Extracted("txt", (Section(None, text),), None, cut)
    if not any(s.text.strip() for s in result.sections):
        raise DocumentRefusedError("no_text" if kind == "pdf" else "empty")
    return result


def clean(text: str) -> str:
    text = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    return _BLANK_LINES.sub("\n\n", _SPACES.sub("\n", text)).strip()


def _limit(text: str) -> tuple[str, bool]:
    return (text[:MAX_CHARS], True) if len(text) > MAX_CHARS else (text, False)


def _decode(data: bytes) -> str:
    """UTF-8 (with or without BOM), UTF-16 with a BOM, else Turkish Windows (cp1254)."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    elif data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError:
            raise DocumentRefusedError("encoding") from None
    if b"\x00" in data[:8192]:
        raise DocumentRefusedError("binary")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1254")
    except UnicodeDecodeError:
        raise DocumentRefusedError("encoding") from None


def _pdf(data: bytes) -> Extracted:
    if b"%PDF-" not in data[:1024]:
        raise DocumentRefusedError("unreadable")
    from pypdf import PdfReader  # only this module parses PDFs (import-linter)

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise DocumentRefusedError("encrypted")
        count = len(reader.pages)
    except DocumentRefusedError:
        raise
    except Exception:
        raise DocumentRefusedError("unreadable") from None
    sections: list[Section] = []
    total = 0
    truncated = count > MAX_PAGES
    started = time.monotonic()
    for index in range(min(count, MAX_PAGES)):
        if time.monotonic() - started > MAX_SECONDS:
            truncated = True
            break
        try:
            raw = reader.pages[index].extract_text() or ""
        except Exception:
            raw = ""  # one broken page does not lose the others
        text = clean(raw)
        if total + len(text) > MAX_CHARS:
            text = text[: MAX_CHARS - total]
            truncated = True
        total += len(text)
        sections.append(Section(index + 1, text))
        if truncated and total >= MAX_CHARS:
            break
    return Extracted("pdf", tuple(sections), count, truncated)


def _docx(data: bytes) -> Extracted:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        info = archive.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError):
        raise DocumentRefusedError("unreadable") from None
    if info.file_size > MAX_DOCX_XML:
        raise DocumentRefusedError("too_large", status=413)
    try:
        with archive.open(info) as stream:
            xml = stream.read(MAX_DOCX_XML + 1)  # the header can lie about the size
    except (zipfile.BadZipFile, OSError, RuntimeError):
        raise DocumentRefusedError("unreadable") from None
    if len(xml) > MAX_DOCX_XML:
        raise DocumentRefusedError("too_large", status=413)
    if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
        raise DocumentRefusedError("unreadable")  # a Word document never has a DTD
    try:
        # No DTD reaches the parser (refused above): no entity expansion, no external entity.
        root = ElementTree.fromstring(xml)  # noqa: S314
    except ElementTree.ParseError:
        raise DocumentRefusedError("unreadable") from None
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{_W}p"):
        parts: list[str] = []
        for el in paragraph.iter():
            if el.tag == f"{_W}t":
                parts.append(el.text or "")
            elif el.tag == f"{_W}tab":
                parts.append("\t")
            elif el.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    text, cut = _limit(clean("\n".join(paragraphs)))
    return Extracted("docx", (Section(None, text),), None, cut)
