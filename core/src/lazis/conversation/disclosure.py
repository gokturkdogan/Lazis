"""The model's internal layers never reach the user (Phase 9 final corrections, ADR-0020).

The system message, its context blocks ("=== BİLGİ … ===", "=== KİŞİSEL HAFIZA … ===") and the
note about this turn's memory operation ("=== SİSTEM NOTU … ===") are for the model. The
persona tells it not to name them; it still does, rarely ("Sistem notlarında belirttiğim gibi
…", Phase 7.2 l06, one run in five). This guard enforces the rule on the reply text itself,
deterministically and with no model call, before anything is shown or stored:

* **labels** — the blocks' own names and markers ("SİSTEM NOTU", "HAFIZA İŞLEMİ", "BİLGİ
  bloğu", "KİŞİSEL HAFIZA", "talimat değildir", "===", the memory states' identifiers),
  always;
* **LAZIS's own instructions used as a source** — an instruction word that is LAZIS's
  ("talimatlarım", "promptumda", "bana verilen talimatlar", "gizli / iç / dahili / geliştirici
  talimatı", "arka plandaki sistem talimatı") cited ("… göre", "… belirtildiği gibi", "… bana
  şunu söylüyor", "… tanımlandım"). "Sistem talimatı" alone is how one explains a language
  model; it counts only together with LAZIS in the first person.

Not: the words as such. "LAZIS'in hafıza sistemi", "bir dil modeline sistem promptu verilir",
"talimatlarınızı" and quoted text stay.

A citation frame is dropped and the sentence kept ("Sistem notlarında belirttiğim gibi, bunu
bilmiyorum." → "Bunu bilmiyorum."); any other sentence with such a reference is dropped whole.
A reply left with nothing says so in one neutral sentence.

Streaming works like the claim guard (:mod:`lazis.memory.claims`): text is released up to the
word before one that may begin a reference, which is held until its sentence ends. Released
text is final, so the user never sees a reference that is taken back, and the stored reply is
the shown text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from lazis.memory.claims import ClaimState, fold

FALLBACK = "Bunu bu şekilde açıklayamıyorum; başka nasıl yardımcı olabilirim?"
MAX_HOLD = 240  # characters held without a sentence end before deciding at a word boundary

# Labels, in the original casing (as the blocks write them) and folded.
_LABEL_RAW = re.compile(
    r"={2,}|SİSTEM\s+NOTU|HAFIZA\s+İŞLEM|KİŞİSEL\s+HAFIZA|BİLGİ\s+SONU|BİLGİ\s*\(|"
    r"TALİMAT\s+DEĞİLDİR|BİLGİDİR"
)
_STATES = "|".join([s.value for s in ClaimState] + ["confirm_needed"])
_LABEL = re.compile(
    r"\bsistem\s+not\w*|\b(?:bilgi|hafiza|baglam)\s+blo[kg]\w*|'bilgi'\s+(?:bolum|blo[kg])\w*"
    r"|\bhafiza\s+islemi\s*:|\btalimat\s+degildir\b|\b(?:" + _STATES + r")\b"
)
_NOUN = r"(?:talimat|yonerge|prompt|istem\b|sistem\s+mesaj|gelistirici\s+mesaj)"
# LAZIS's own: given to it, hidden, internal, or in its first-person possessive.
_OWNED = re.compile(
    r"\b(?:bana\s+(?:verilen|verilmis|iletilen|tanimlanan|yuklenen)\s+(?:\w+\s+)?"
    r"|(?:gizli|ic|dahili|gelistirici|arka\s+plandaki)\s+(?:sistem\s+)?)" + _NOUN + r"\w*"
    r"|\b(?:talimat(?:lar)?im|yonerge(?:ler)?i?m|prompt(?:lar)?[iu]?m|istemim"
    r"|(?:sistem|gelistirici)\s+mesaj(?:lar)?im)\w*"
)
_SYSTEM = re.compile(r"\bsistem\s+(?:talimat|yonerge|prompt|istem|mesaj)\w*")
_CITE = re.compile(
    r"\b(?:gore|geregi|uyarinca|dogrultusunda|cercevesinde|uzere|gibi)\b"
    r"|\b(?:belirt|yaz|soyl|tanimla|ifade ed|ongor|emr|isten|de(?:n|di|r)\b|diyor|deniyor"
    r"|gec(?:iyor|ti|en|tig)|bildir|yasakl|izin ver|tembih)\w*"
)
_FIRST = re.compile(
    r"\b(?:bana|beni|benim|bende|benden)\b"
    r"|\w(?:[dt][iu]m|[dt][iu]g[iu]m|yorum|c[ae]g[iu]m|l[ae]nd[iu]m|m[ae]l[iu]y[iu]m)\b"
)
_CLOSE = re.compile(
    r"(?:\s+[a-z0-9']+){0,3}?\s+(?:gore|geregi|uyarinca|dogrultusunda|cercevesinde|gibi|uzere)\b"
    r"[,;]?\s*"
)
# Not at ":": what follows "talimatım şunu söylüyor:" is part of the reference.
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)|\n+")
_WORD = re.compile(r"[a-z0-9_']+")


def _quoted(text: str) -> list[tuple[int, int]]:
    rx = r'"[^"]*"|“[^”]*”|«[^»]*»'
    return [(m.start(), m.end()) for m in re.finditer(rx, text)]


def find_refs(sentence: str) -> list[tuple[int, int]]:
    """Spans of internal references in one sentence (indices into ``sentence``)."""
    f = fold(sentence)
    found = [(m.start(), m.end()) for m in _LABEL_RAW.finditer(sentence)]
    found += [(m.start(), m.end()) for m in _LABEL.finditer(f)]
    quotes = _quoted(sentence)
    cited = _CITE.search(f) is not None
    first = _FIRST.search(f) is not None
    for rx, needs_first in ((_OWNED, False), (_SYSTEM, True)):
        for m in rx.finditer(f):
            if any(a <= m.start() < b for a, b in quotes):
                continue  # the user's words, quoted
            if cited and (first or not needs_first):
                found.append((m.start(), m.end()))
    return sorted(set(found))


def rewrite_sentence(sentence: str, *, frozen: int = 0) -> tuple[str, int]:
    """The sentence without its internal references, and how many were removed. Characters
    before ``frozen`` were already shown and are never changed."""
    removed = 0
    out = sentence
    for _ in range(4):
        refs = [r for r in find_refs(out) if r[1] > frozen]
        if not refs:
            return out, removed
        removed += 1
        a, b = refs[0]
        a = max(a, frozen)
        close = _CLOSE.match(fold(out), b)
        rest = out[close.end() :] if close else ""
        if not re.search(r"\w", rest):
            return _drop(out, frozen), removed  # not a frame, or nothing but the frame
        if not out[:a].strip() or out[:a].rstrip()[-1:] in ".!?\n":
            out = out[:a] + _upper_first(rest)  # "Sistem notlarında belirttiğim gibi, X"
        else:
            head = out[:frozen] + re.sub(r"[\s,;]+$", "", out[frozen:a])
            out = head + ("" if head[-1:].isspace() else " ") + rest  # "Bunu, … gibi, X"
    return _drop(out, frozen), removed


def _upper_first(text: str) -> str:
    m = re.search(r"\w", text)
    if m is None:
        return text
    ch = text[m.start()]
    up = "İ" if ch == "i" else "I" if ch == "ı" else ch.upper()
    return text[: m.start()] + up + text[m.start() + 1 :]


def _drop(sentence: str, frozen: int) -> str:
    """The unshown part of the sentence removed; its line breaks stay."""
    breaks = re.search(r"\n*$", sentence[frozen:].rstrip(" \t"))
    return sentence[:frozen] + (breaks.group(0) if breaks else "")


_RISKY = ("sistem", "talimat", "yonerge", "prompt", "gelistirici", "gizli", "dahili", "arka",
          "kisisel", "hafiza", "baglam")  # fmt: skip


def _risky_word(w: str) -> bool:
    w = w.strip("'")
    return (
        "_" in w
        or w.startswith(_RISKY)
        or w in ("bana", "benim", "ic", "bilgi")
        or re.fullmatch(r"istem(?:im\w*|i|in|e|de|den)?", w) is not None
    )


@dataclass
class DisclosureGuard:
    """Streams a reply through the disclosure rules. ``feed`` returns what is safe to show
    now, ``finish`` the rest."""

    released: str = ""
    pending: str = ""
    removed: int = 0

    def feed(self, chunk: str) -> str:
        self.pending += chunk
        return self._release(final=False)

    def finish(self) -> str:
        out = self._release(final=True)
        if self.removed and not self.released.strip():
            self.released += FALLBACK  # the reply was nothing but references
            out += FALLBACK
        return out

    def _risky_at(self, f: str) -> int | None:
        eq = f.find("=")
        for m in _WORD.finditer(f):
            if eq != -1 and eq < m.start():
                return eq
            if _risky_word(m.group(0)):
                return m.start()
        return None if eq == -1 else eq

    def _emit(self, n: int) -> str:
        piece, self.pending = self.pending[:n], self.pending[n:]
        return self._add(piece)

    def _add(self, piece: str) -> str:
        if self.removed and not self.released.strip():
            piece = piece.lstrip()  # a reply whose first sentence was dropped
        self.released += piece
        return piece

    def _release(self, *, final: bool) -> str:
        out = ""
        while self.pending:
            f = fold(self.pending)
            risky = self._risky_at(f)
            if risky is None:
                n = len(self.pending) if final else _before_last_word(f)
                if n == 0:
                    break
                out += self._emit(n)
                continue
            hold_from = _before_last_word(f[:risky])
            if hold_from > 0:
                out += self._emit(hold_from)
                continue
            end = _sentence_end(self.pending, final)
            if end is None:
                if len(self.pending) < MAX_HOLD:
                    break
                end = self.pending.rfind(" ", 0, MAX_HOLD) + 1 or MAX_HOLD
            start = _sentence_start(self.released)
            sentence = self.released[start:] + self.pending[:end]
            frozen = len(self.released) - start
            new, removed = rewrite_sentence(sentence, frozen=frozen)
            self.removed += removed
            self.pending = self.pending[end:]
            out += self._add(new[frozen:])
        return out


def check(text: str) -> tuple[str, int]:
    """The whole reply at once (the same result as streaming it)."""
    guard = DisclosureGuard()
    out = guard.feed(text) + guard.finish()
    return out, guard.removed


def _before_last_word(f: str) -> int:
    """Where the held tail begins: the last word (it may be incomplete) with the space before
    it — and the word before that too when the last one may still become a risky word."""
    words = list(_WORD.finditer(f))
    if not words:
        return 0
    keep = words[-1]
    if len(words) > 1 and _could_become_risky(keep.group(0)):
        keep = words[-2]
    m = re.search(r"\s*$", f[: keep.start()])
    return m.start() if m is not None else keep.start()


def _could_become_risky(w: str) -> bool:
    w = w.strip("'")
    prefixes = ("sistem", "talimat", "yonerge", "prompt", "gelistirici", "gizli", "dahili", "arka",
                "kisisel", "hafiza", "baglam", "bana", "benim", "bilgi", "istem")  # fmt: skip
    return any(p.startswith(w) for p in prefixes) or w == "i"


def _sentence_end(text: str, final: bool) -> int | None:
    for m in _SENTENCE_END.finditer(text):
        if m.end() < len(text) or final:
            return m.end()
    return len(text) if final else None


def _sentence_start(text: str) -> int:
    best = 0
    for m in _SENTENCE_END.finditer(text):
        best = m.end()
    return best
