"""Turkish forms of address — the "sen" preference (layer 2, Phase 10B, ADR-0022).

Pure: which words of a reply address the user as "siz" and their "sen" form. Turkish marks
the person in suffixes, so "siz deme" covers far more than the pronoun:

* pronouns — siz, size, sizi, sizin, sizce, sizde, sizden, sizinle → sen, sana, seni, …;
* the second person plural ending on verbs and nouns, with any case after it —
  yapabilirsiniz, yapıyorsunuz, yaptınız, isterseniz, olursanız, ister misiniz, ihtiyacınız,
  ihtiyacınıza, evinizde → yapabilirsin, yapıyorsun, yaptın, istersen, olursan, ister misin,
  ihtiyacın, ihtiyacına, evinde (the ``-ız`` after the ``n`` goes; what follows stays);
* the plural imperative — deneyin, unutmayın, izleyin, yapın, edin, dikkatli olun → dene,
  unutma, izle, yap, et, dikkatli ol.

What is not LAZIS talking to the user is left alone: code, quotations, ``>`` quoted lines and
a sample letter or message (from its salutation to its closing), where "siz" is right for the
person it is written to. So are the words that only look plural: deniz, Akdeniz, yalnız, hepiniz
(a group), and nouns whose genitive looks like an imperative (olayın, uzayın, deneyin …) unless
punctuation follows, where a genitive cannot stand.

:func:`plural_forms` lists what :func:`to_sen` would change; :class:`AddressGuard` applies it
to a streamed reply, one whole word at a time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_LETTERS = "a-zçğıöşüâîû"
_WORD = re.compile(rf"[{_LETTERS}A-ZÇĞİÖŞÜÂÎÛ]+")

PRONOUNS = {
    "siz": "sen",
    "size": "sana",
    "sizi": "seni",
    "sizin": "senin",
    "sizce": "sence",
    "sizde": "sende",
    "sizden": "senden",
    "sizinle": "seninle",
    "sizinki": "seninki",
    "sizinkini": "seninkini",
    "sizlere": "sana",
}

# A vowel, then the plural "n" + "ız" (person or possessive), then case endings.
_PLURAL = re.compile(rf"^(?P<stem>[{_LETTERS}]*[aeıioöuü]n)(?P<z>[ıiuü]z)(?P<rest>[{_LETTERS}]*)$")
_AFTER = frozenset(
    {"", "ı", "i", "u", "ü", "a", "e", "da", "de", "ta", "te", "dan", "den", "tan", "ten",
     "ın", "in", "un", "ün", "la", "le", "dır", "dir", "dur", "dür", "tır", "tir", "tur",
     "tür", "daki", "deki", "taki", "teki", "ca", "ce"}
)  # fmt: skip
# Words that end like the plural but are not "you": the sea, "pale", "stubble", "alone" and
# the group quantifiers (addressing several people, not the user in "siz").
# "-ize" loans (organize, senkronize) end the same way too.
NOT_PLURAL = ("beniz", "anız", "yalnız", "hepiniz", "ikiniz", "üçünüz", "çoğunuz",
               "birçoğunuz", "bazılarınız", "kiminiz", "herbiriniz", "biriniz", "hanginiz",
               "organiz", "mekaniz", "senkroniz", "harmoniz", "koloniz", "romaniz", "minimiz",
               "kanoniz", "ironiz")  # fmt: skip

# Plural imperative after a vowel stem: dene-yin, unutma-yın, izle-yin, ara-yın, oku-yun.
_Y_IMPERATIVE = re.compile(rf"^(?P<stem>[{_LETTERS}]{{2,}}[aeıioöuü])y[ıiuü]n$")
# Nouns in -y whose genitive reads the same ("olayın sonucu"): an imperative only before
# punctuation.
_Y_NOUNS = frozenset({"olay", "kolay", "alay", "saray", "uzay", "deney", "düzey", "yüzey",
                      "hokey", "jokey", "kurultay", "ilay", "aday", "obje"})  # fmt: skip
# Causatives: çalıştır-ın, karıştır-ın, değiştir-in (the "-tır/-dır" before "-ın").
_CAUSATIVE = re.compile(rf"^(?P<stem>[{_LETTERS}]{{3,}}[td][ıiuü]r)[ıiuü]n$")
# Consonant stems: a closed list, since "-ın" is also "your" / "of" (kitabın, evin).
IMPERATIVES = {
    "yapın": "yap", "bakın": "bak", "edin": "et", "edinin": "edin", "verin": "ver",
    "seçin": "seç", "gidin": "git", "kullanın": "kullan", "oluşturun": "oluştur",
    "ayırın": "ayır", "bırakın": "bırak", "çıkarın": "çıkar", "düşünün": "düşün",
    "girin": "gir", "unutun": "unut", "çalışın": "çalış", "geçin": "geç", "gönderin": "gönder",
    "açın": "aç", "kapatın": "kapat", "başlatın": "başlat", "öğrenin": "öğren",
    "kaçının": "kaçın", "yiyin": "ye", "olun": "ol", "bulun": "bul", "katılın": "katıl",
    "tutun": "tut", "alın": "al", "sorun": "sor", "gelin": "gel", "kalın": "kal",
    "yazın": "yaz", "koyun": "koy", "çizin": "çiz", "silin": "sil", "durun": "dur",
    "inin": "in", "binin": "bin", "yürütün": "yürüt", "uyun": "uy", "iyileştirin": "iyileştir",
    "belirtin": "belirt", "değiştirin": "değiştir", "ölçün": "ölç", "tartın": "tart",
    "pişirin": "pişir", "karıştırın": "karıştır", "ekin": "ek", "dökün": "dök", "kesin": "kes",
    "isteyin": "iste", "gösterin": "göster", "götürün": "götür", "getirin": "getir",
}  # fmt: skip
# Of those, the ones that are also an everyday noun form (alın = forehead, sorun = problem,
# gelin = bride, kalın = thick, yazın = in summer, koyun = sheep, kesin = certain, ekin =
# crop, uyun …): an imperative only before punctuation.
_AMBIGUOUS = frozenset({"alın", "sorun", "gelin", "kalın", "yazın", "koyun", "kesin", "ekin",
                        "uyun", "inin", "tutun", "durun"})  # fmt: skip

_SALUTATION = re.compile(
    r"^[\W_]*(sayın|merhaba|değerli|sevgili|kıymetli|selam|dear|hello|konu:)", re.I
)
_CLOSING = re.compile(
    r"^[\W_]*(saygılarımla|saygılar|iyi çalışmalar|sevgiler|teşekkürler|best|regards|kind)",
    re.I,
)
_QUOTE_OPEN = {"“": "”", "«": "»", '"': '"', "„": "”"}


def lower(word: str) -> str:
    return word.replace("I", "ı").replace("İ", "i").lower()


def _cased(original: str, new: str) -> str:
    if original[:1].isupper():
        head = {"i": "İ", "ı": "I"}.get(new[:1], new[:1].upper())
        if original.isupper() and len(original) > 1:
            return (head + new[1:]).replace("i", "İ").replace("ı", "I").upper()
        return head + new[1:]
    return new


def to_sen(word: str, *, before_punct: bool = False) -> str | None:
    """The "sen" form of one word addressing the user as "siz", or None (not such a word).
    ``before_punct``: punctuation follows the word (a genitive cannot stand there)."""
    w = lower(word)
    if w in PRONOUNS:
        return _cased(word, PRONOUNS[w])
    if "deniz" in w or w.startswith(NOT_PLURAL):
        return None
    m = _PLURAL.match(w)
    if m and m.group("rest") in _AFTER and len(m.group("stem")) >= 2:
        return _cased(word, m.group("stem") + m.group("rest"))
    if w in IMPERATIVES:
        if w in _AMBIGUOUS and not before_punct:
            return None
        return _cased(word, IMPERATIVES[w])
    m = _CAUSATIVE.match(w)
    if m:
        return _cased(word, m.group("stem"))
    m = _Y_IMPERATIVE.match(w)
    if m and (before_punct or m.group("stem") + "y" not in _Y_NOUNS):
        return _cased(word, m.group("stem"))
    return None


@dataclass
class _Spans:
    """Where the text is not LAZIS talking to the user (code, quotes, a sample letter)."""

    fence: bool = False
    inline: bool = False
    quote: str = ""  # the closing quote mark while inside a quotation
    line_quote: bool = False  # a ``>`` line
    sample: bool = False  # a sample letter / message
    closing: bool = False  # the sample's closing line: it ends with the line
    line_start: bool = True
    first_line: bool = True  # a greeting on the reply's first line is LAZIS's own
    newlines: int = 0  # line breaks since the last token: a blank line closes a stray quote

    @property
    def quiet(self) -> bool:
        return self.fence or self.inline or bool(self.quote) or self.line_quote or self.sample

    def newline(self) -> None:
        self.line_quote = False
        self.first_line = False
        self.newlines += 1
        if self.newlines >= 2:
            self.quote = ""
        if self.closing:
            self.sample = self.closing = False
        self.line_start = True


def _convert(
    text: str,
    spans: _Spans,
    found: list[str] | None,
    spoken: list[tuple[str, bool]] | None = None,
) -> str:
    """Convert whitespace-delimited ``text`` (whole tokens), updating ``spans``."""
    out: list[str] = []
    for part in re.split(r"(\s+)", text):
        if not part:
            continue
        if part.isspace():
            for _ in range(part.count("\n")):
                spans.newline()
            out.append(part)
            continue
        out.append(_token(part, spans, found, spoken))
        spans.line_start = False
        spans.newlines = 0
    return "".join(out)


def _token(
    tok: str, spans: _Spans, found: list[str] | None, spoken: list[tuple[str, bool]] | None
) -> str:
    if tok.startswith("```"):
        spans.fence = not spans.fence
        return tok
    if spans.fence:
        return tok
    if spans.line_start:
        if tok.startswith(">"):
            spans.line_quote = True
        if spans.sample and (tok.startswith("#") or tok.startswith("**") or tok == "---"):
            spans.sample = False
        if _SALUTATION.match(tok) and not spans.first_line:
            spans.sample = True
        elif spans.sample and _CLOSING.match(tok):
            spans.closing = True
    if "://" in tok or "@" in tok:
        return tok
    out: list[str] = []
    pos = 0
    for m in _WORD.finditer(tok):
        out.append(_marks(tok[pos : m.start()], spans, start=pos == 0, end=False))
        word = m.group(0)
        after = tok[m.end() : m.end() + 1]
        new = None
        if not spans.quiet:
            punct = bool(after) and after in ".,;:!?)…"
            new = to_sen(word, before_punct=punct)
            if spoken is not None:
                spoken.append((word, punct))
        if new is not None and found is not None:
            found.append(word)
        out.append(new if new is not None else word)
        pos = m.end()
    out.append(_marks(tok[pos:], spans, start=pos == 0, end=True))
    return "".join(out)


def _marks(s: str, spans: _Spans, *, start: bool, end: bool) -> str:
    """Code and quotation marks between words. A single quote opens only where a token
    starts and closes only where one ends: inside a word it is the apostrophe (İstanbul'da)."""
    for ch in s:
        if ch in "'‘’":
            if spans.quote in ("'", "’") and end and ch in "'’":
                spans.quote = ""
            elif not spans.quote and start and ch in "'‘":
                spans.quote = "'" if ch == "'" else "’"
        elif ch == "`":
            spans.inline = not spans.inline
        elif spans.quote:
            if ch == spans.quote:
                spans.quote = ""
        elif ch in _QUOTE_OPEN:
            spans.quote = _QUOTE_OPEN[ch]
    return s


def plural_forms(text: str | None) -> list[str]:
    """The words of ``text`` that address the user as "siz" (outside code, quotes and
    sample letters)."""
    found: list[str] = []
    _convert(text or "", _Spans(), found)
    return found


def spoken_words(text: str | None) -> list[tuple[str, bool]]:
    """The words of ``text`` LAZIS says to the user (outside code, quotes and sample letters),
    each with whether punctuation follows it — for checks independent of :func:`to_sen`."""
    spoken: list[tuple[str, bool]] = []
    _convert(text or "", _Spans(), None, spoken)
    return spoken


def to_sen_text(text: str) -> str:
    """The whole text with its "siz" forms turned into "sen" (same result as streaming)."""
    guard = AddressGuard()
    return guard.feed(text) + guard.finish()


@dataclass
class AddressGuard:
    """Streams a reply, releasing whole tokens with their "siz" forms in "sen". A quotation
    left open closes at a blank line, so a stray quote mark cannot switch the guard off for
    the rest of the reply."""

    released: str = ""
    pending: str = ""
    changed: list[str] = field(default_factory=list[str])
    _spans: _Spans = field(default_factory=_Spans)

    def feed(self, chunk: str) -> str:
        self.pending += chunk
        cut = max(self.pending.rfind(" "), self.pending.rfind("\n"), self.pending.rfind("\t"))
        if cut < 0:
            return ""
        return self._release(self.pending[: cut + 1], self.pending[cut + 1 :])

    def finish(self) -> str:
        return self._release(self.pending, "")

    def _release(self, ready: str, rest: str) -> str:
        piece = _convert(ready, self._spans, self.changed)
        self.pending = rest
        self.released += piece
        return piece
