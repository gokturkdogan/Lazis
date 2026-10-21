"""Reading a profile file (Phase 8): format, size, encoding, binary content, safe names,
sections with exact file lines, secrets redacted before the model or the draft see them.
Synthetic data only."""

from __future__ import annotations

import pytest

from lazis.bootstrap import files


@pytest.mark.parametrize(
    ("name", "fmt"),
    [("profil.md", "markdown"), ("Profil.MARKDOWN", "markdown"), ("notlar.txt", "text"),
     ("ben.json", "json"), ("a.b.c.md", "markdown")],
)  # fmt: skip
def test_format_comes_from_the_extension(name: str, fmt: str) -> None:
    assert files.format_for(name) == fmt


@pytest.mark.parametrize(
    "name", ["profil.pdf", "profil.docx", "profil", "profil.md.exe", "profil.mdx"]
)
def test_other_formats_are_refused(name: str) -> None:
    with pytest.raises(files.FileRejected) as e:
        files.read(name, b"Merhaba")
    assert e.value.code == "unsupported_format"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "empty"),
        (b"  \n\t \n", "empty"),
        (b"a" * (files.MAX_FILE_BYTES + 1), "too_large"),
        (b"\x00\x01\x02\x03binary", "binary"),
        (bytes(range(1, 32)) * 10, "binary"),
        ("Çalışıyorum".encode("latin-1", "replace") + b"\xe7\xfe", "encoding"),
        (b"\xff\xd8\xff\xe0JFIF", "encoding"),
    ],
)
def test_bad_content_is_refused_with_its_reason(data: bytes, code: str) -> None:
    with pytest.raises(files.FileRejected) as e:
        files.read("p.txt", data)
    assert e.value.code == code


def test_too_long_text_is_refused() -> None:
    data = ("ş" * (files.MAX_TEXT_CHARS + 10)).encode()
    if len(data) > files.MAX_FILE_BYTES:  # the byte limit comes first for multi-byte text
        data = ("a\n" * (files.MAX_TEXT_CHARS // 2 + 10)).encode()
    with pytest.raises(files.FileRejected) as e:
        files.read("p.txt", data)
    assert e.value.code in ("too_long", "too_large")


@pytest.mark.parametrize(
    "data",
    [
        "Meslek: mimar\nŞehir: İzmir".encode(),
        b"\xef\xbb\xbf" + "Meslek: mimar\nŞehir: İzmir".encode(),
        "Meslek: mimar\r\nŞehir: İzmir".encode(),
        "Meslek: mimar\nŞehir: İzmir".encode("utf-16"),
    ],
)
def test_utf8_bom_utf16_and_line_endings_are_read_the_same(data: bytes) -> None:
    f = files.read("p.txt", data)
    assert f.text == "Meslek: mimar\nŞehir: İzmir"


@pytest.mark.parametrize(
    ("name", "safe"),
    [("../../etc/passwd.md", "passwd.md"), ("C:\\Users\\x\\Belgeler\\profil.md", "profil.md"),
     ("/Users/x/profil.json", "profil.json"), ("profil.txt", "profil.txt")],
)  # fmt: skip
def test_only_the_base_name_is_kept(name: str, safe: str) -> None:
    assert files.read(name, b"Meslek: mimar").name == safe


def test_same_bytes_same_hash_and_size() -> None:
    a, b = files.read("a.txt", b"Meslek: mimar"), files.read("b.txt", b"Meslek: mimar")
    assert a.content_hash == b.content_hash and a.size_bytes == 13
    assert files.read("c.txt", b"Meslek: pilot").content_hash != a.content_hash


MD = """# Hakkımda
Meslek: veri analisti

Şehir: İzmir

## Aile
### Kardeşlerim
Elif öğretmen.

# Projeler
Atlas bir not uygulaması.
"""


def test_markdown_sections_keep_heading_paths_and_file_lines() -> None:
    f = files.read("p.md", MD.encode())
    heads = [s.heading for s in f.sections]
    assert heads == ["Hakkımda", "Hakkımda › Aile › Kardeşlerim", "Projeler"]
    lines = MD.split("\n")
    for s in f.sections:
        for body_line, n in zip(s.body.split("\n"), s.line_numbers, strict=True):
            assert lines[n - 1].strip() == body_line.strip()
    elif_ = f.sections[1]
    assert files.line_of(elif_, "Elif öğretmen") == 8
    assert files.line_of(f.sections[0], "İzmir") == 4
    assert files.line_of(f.sections[0], "Ankara") is None


def test_long_text_is_split_into_bounded_sections_with_lines() -> None:
    paras = [f"Paragraf {i}: " + "kelime " * 40 for i in range(60)]
    raw = "\n\n".join(paras)
    f = files.read("p.txt", raw.encode())
    assert len(f.sections) > 5
    assert all(len(s.body) <= files.SECTION_CHARS + 400 for s in f.sections)
    covered = sorted(n for s in f.sections for n in s.line_numbers)
    assert covered == sorted(i * 2 + 1 for i in range(60))  # every paragraph line, once
    assert [s.idx for s in f.sections] == list(range(len(f.sections)))


def test_secret_lines_are_redacted_before_anything_sees_them() -> None:
    raw = "Meslek: mimar\nKart şifrem 4471\nparolam: Yaz2026!\nŞehir: İzmir"
    f = files.read("p.txt", raw.encode())
    assert f.redacted_lines == (2, 3)
    assert "4471" not in f.text and "Yaz2026" not in f.text
    assert all("4471" not in s.body for s in f.sections)
    assert f.text.split("\n")[1] == files.REDACTED


def test_control_characters_are_dropped_not_kept() -> None:
    f = files.read("p.txt", b"Meslek:\x07 mimar\x1b[31m")
    assert "\x07" not in f.text and "\x1b" not in f.text
