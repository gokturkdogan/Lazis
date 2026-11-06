"""Text out of a chosen document (Phase 11): TXT, PDF text layer, DOCX, and every refusal."""

from __future__ import annotations

import pytest

from lazis.documents import extract
from lazis.documents.extract import MAX_BYTES
from lazis.errors import DocumentRefusedError
from tests.document_support import docx, pdf


def refused(name: str, data: bytes) -> str:
    with pytest.raises(DocumentRefusedError) as caught:
        extract(name, data)
    return caught.value.code


def test_txt_in_utf8_utf16_and_turkish_windows() -> None:
    text = "Şirket çalışanları ığdır'da toplandı.\r\nİkinci satır."
    for data in (text.encode(), b"\xef\xbb\xbf" + text.encode(), text.encode("utf-16"),
                 text.encode("cp1254")):  # fmt: skip
        out = extract("notlar.TXT", data)
        assert out.kind == "txt" and out.pages is None and not out.truncated
        assert out.sections[0].text == "Şirket çalışanları ığdır'da toplandı.\nİkinci satır."


def test_pdf_text_layer_by_page() -> None:
    out = extract("rapor.pdf", pdf("Birinci sayfa metni", "Ikinci sayfa metni"))
    assert out.kind == "pdf" and out.pages == 2
    assert [(s.page, s.text) for s in out.sections] == [
        (1, "Birinci sayfa metni"), (2, "Ikinci sayfa metni")]  # fmt: skip


def test_docx_paragraphs() -> None:
    out = extract("karar.docx", docx("Toplantı kararları", "Bütçe onaylandı."))
    assert out.kind == "docx" and out.sections[0].text == "Toplantı kararları\nBütçe onaylandı."


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("tablo.xlsx", b"PK", "document_unsupported"),
        ("adsiz", b"metin", "document_unsupported"),
        ("bos.txt", b"", "document_empty"),
        ("bosluk.txt", b"  \n\n ", "document_empty"),
        ("ikili.txt", b"abc\x00\x01\x02", "document_binary"),
        ("bozuk.pdf", b"%PDF-1.4 bozuk", "document_unreadable"),
        ("degil.pdf", b"merhaba", "document_unreadable"),
        ("tarama.pdf", pdf(""), "document_no_text"),
        ("bozuk.docx", b"PK\x03\x04 bozuk", "document_unreadable"),
        ("zip.docx", docx(xml=b"<x/>")[:30], "document_unreadable"),
    ],
)
def test_refusals_name_the_reason(name: str, data: bytes, code: str) -> None:
    assert refused(name, data) == code


def test_a_docx_with_a_dtd_is_refused_before_parsing() -> None:
    bomb = (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaa">'
            b'<!ENTITY b "&a;&a;&a;&a;">]><x>&b;</x>')  # fmt: skip
    assert refused("bomba.docx", docx(xml=bomb)) == "document_unreadable"


def test_too_large() -> None:
    with pytest.raises(DocumentRefusedError) as caught:
        extract("buyuk.txt", b"a" * (MAX_BYTES + 1))
    assert caught.value.code == "document_too_large" and caught.value.http_status == 413


def test_the_refusal_carries_no_content() -> None:
    with pytest.raises(DocumentRefusedError) as caught:
        extract("gizli.pdf", b"%PDF-1.4 Gizli-Musteri-Listesi")
    assert "Gizli" not in str(caught.value) and "Gizli" not in caught.value.code
