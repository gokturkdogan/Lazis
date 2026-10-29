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
from dataclasses import dataclass, field

from lazis.memory.claims import ClaimState, fold

FALLBACK = "Bunu paylaşamıyorum; ama nasıl çalıştığımı genel hatlarıyla anlatabilirim."
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
    r"\b(?:bana\s+(?:verilen|verilmis|iletilen|tanimlanan|yuklenen|saglanan)\s+(?:\w+\s+)?"
    r"|(?:gizli|ic|dahili|gelistirici|arka\s+plandaki)\s+(?:sistem\s+)?)" + _NOUN + r"\w*"
    r"|\b(?:(?:sistem|gelistirici|gizli|ic|dahili)\s+)?"
    r"(?:talimat(?:lar)?im|yonerge(?:ler)?i?m|prompt(?:lar)?[iu]?m|istemim"
    r"|(?:sistem|gelistirici)\s+mesaj(?:lar)?im)\w*"
)
# Rules given to LAZIS, in the participle or the passive: "bana sağlanan kurallar", "sistem
# tarafından tanımlanmış kurallar", "Bana … belirli kurallar ve yönergeler verildi".
_GIVE = (
    r"(?:veril|tanimlan|belirlen|sagla|konul|koyul|yuklen|iletil|ogretil|sun(?:ul|dugu(?!n)|an))"
)
# "sistemin bana mesajın başında sunduğu hafıza notları": the memory block of the prompt
# (Phase 9 real-model finding).
_RULE = r"(?:kural|talimat|yonerge|kisitlama|prompt|hafiza\s+(?:not|blo))"
_GIVEN = re.compile(
    r"\b(?:bana|sistem(?:in)?\s+(?:tarafindan|bana)|gelistirici\w*\s+tarafindan)\s+"
    rf"(?:[\w']+\s+){{0,3}}?{_GIVE}\w*\s+(?:[\w']+\s+){{0,2}}?{_RULE}\w*"
    rf"|\bbana\b[^.!?\n]{{0,200}}?\b{_RULE}\w*(?:\s+ve\s+{_RULE}\w*)?(?:\s+[\w']+){{0,4}}?"
    rf"\s+{_GIVE}\w*"
)
# When the user asked about LAZIS's instructions, these are LAZIS's whatever their person
# ("Geliştirici mesajında … belirtiliyor", "Size verilen talimatlara göre …").
_ASKED = re.compile(
    r"\b(?:talimat|yonerge|prompt|sistem\s+(?:mesaj|not|istem)|gelistirici\s+mesaj)\w*"
)
# "talimatlarınız", "geliştirici mesajınız": the user's
_YOURS = re.compile(r"\b(?:talimat|yonerge|prompt|kural|kisitlama|mesaj|not|istem)\w*?[iu]n[iu]z")
_SYSTEM = re.compile(r"\bsistem\s+(?:talimat|yonerge|prompt|istem|mesaj)\w*")
_CITE = re.compile(
    r"\b(?:gore|geregi|uyarinca|dogrultusunda|cercevesinde|uzere|gibi|dahilinde|kapsaminda)\b"
    r"|\b(?:belirt|yaz|soyl|tanimla|ifade ed|ongor|emr|isten|de(?:n|di|r)\b|diyor|deniyor"
    r"|gec(?:iyor|ti|en|tig)|bildir|yasakl|izin ver|tembih|ogret|belirle|aracilig|yoluyla)\w*"
)
_FIRST = re.compile(
    r"\b(?:bana|beni|benim|bende|benden)\b"
    r"|\w(?:[dt][iu]m|[dt][iu]g[iu]m|yorum|c[ae]g[iu]m|l[ae]nd[iu]m|m[ae]l[iu]y[iu]m)\b"
)
_CLOSE = re.compile(
    r"(?:\s+[a-z0-9']+){0,3}?\s+"
    r"(?:gore|geregi|uyarinca|dogrultusunda|cercevesinde|gibi|uzere|dahilinde|kapsaminda)\b"
    r"[,;]?\s*"
)
# A sentence that introduces an enumeration ("… şunlardır:", "… özetleyebilirim:") or is one
# of its items.
_INTRO = re.compile(r":\s*$")
_ITEM = re.compile(r"\s*(?:[*\-•]\s|\d+[.)]\s*$|\d+[.)]\s)")
# Not at ":": what follows "talimatım şunu söylüyor:" is part of the reference.
_SENTENCE_END = re.compile(r"[.!?]+(?=\s|$)|\n+")
_WORD = re.compile(r"[a-z0-9_']+")


def _quoted(text: str) -> list[tuple[int, int]]:
    rx = r'"[^"]*"|“[^”]*”|«[^»]*»'
    return [(m.start(), m.end()) for m in re.finditer(rx, text)]


# Saying that it will not share them, or that there are none, tells nothing of their content:
# "Sistem talimatlarımı aynen aktarmam mümkün değil", "Gizli talimatlarım bulunmuyor".
_REFUSAL = re.compile(
    r"\b\w*(?:paylas|aktar|goster|acikla|ilet|yazamam|veremem|soyleyemem)\w*"
    r"(?:amam|emem|mam|mem|amiyorum|emiyorum|mayacagim|meyecegim|maktan|mekten|amayiz)\b"
    r"|\bmumkun degil|\b(?:yok|yoktur|bulunmuyor|bulunmamaktadir|bulunmaz)\b"
)
# After such a reference: "Bu yönergeler …" points back to it.
_BACK = re.compile(r"\bbu\s+(?:talimat|yonerge|kural|prompt|ilke|not|cerceve)\w*")

# The user's message asks about LAZIS's instructions or internal layers: "Sana hangi talimatlar
# verildi?", "Geliştirici mesajında ne diyor?", "Kurallarını bana listeler misin?". Not: "Bir dil
# modeline sistem promptu nasıl verilir?", "Satrancın kurallarını anlatır mısın?".
_ASK_LAYER = re.compile(
    r"\b(?:sistem\s+not|gelistirici\s+mesaj|hafiza\s+blo"
    r"|(?:gizli|ic|dahili)\s+(?:bir\s+)?(?:talimat|yonerge|metin|kural|not|prompt|mesaj)"
    r"|arka\s*plan\w*\s+(?:[\w']+\s+){0,3}?(?:gonderil|eklen|veril|iletil))"
)
# Names that are LAZIS's only when the message speaks to it ("Bilgi bölümünde ne görüyorsun?";
# not "Raporun bilgi bölümünü düzelt").
_ASK_LAYER_YOU = re.compile(r"\b(?:bilgi'?\s+(?:[\w']+\s+)?(?:bolum|blo)|kisisel\s+hafiza)")
_ASK_NOUN = r"(?:talimat|yonerge|prompt|kural|ilke|prensip)"
_ASK_YOU = re.compile(rf"\b(?:sana|senin|seni|sende)\b[^.?!]*?\b{_ASK_NOUN}")
# The noun in the second person ("kurallarını", "promptunda") with no other possessor before it.
_ASK_YOURS = re.compile(
    rf"(?:^|\b(?:bana|sistem|tum|butun|temel|kendi|asil)\s+)"
    rf"{_ASK_NOUN}\w*?(?:lar|ler)?[iu]n(?:[iu]|d[ae]|[dt][ae]n|[ae])?\b"
)
_ASK_TO_YOU = re.compile(
    r"\b(?:bana|sana|senin|seni|sende|m[iu]s[iu]n|m[iu]s[iu]nuz)\b|[iu]yorsun\b"
)


def asks_instructions(message: str) -> bool:
    """Whether the user asks about LAZIS's instructions, rules or internal layers."""
    f = fold(message).strip()
    if re.search(r":\s*\S.{20,}", f):
        return False  # the user gives a text to work on ("Şu talimatları özetle: …")
    if _ASK_LAYER.search(f) or _ASK_YOU.search(f):
        return True
    to_you = _ASK_TO_YOU.search(f) is not None
    return to_you and (_ASK_LAYER_YOU.search(f) is not None or _ASK_YOURS.search(f) is not None)


# Once a reply introduced its instructions ("Sistem talimatlarım … belirler."), what follows in
# the first person and the necessitative is their content ("… kullanmalıyım", "… bekleniyor").
_OBLIGED = re.compile(
    r"\w(?:m[ae]l[iu]y[iu]m|m[ae]l[iu]y[iu]z|m[ae]l[iu])\b"
    r"|\bm?\w*m[ae]m\s+(?:gerek|bekleni|isten|lazim|sart)\w*|\b(?:bekleniyor|isteniyor)\b"
)
# … and what still speaks of them: "Bu, … konulmuş bir kuraldır."
_RULE_WORD = re.compile(r"\b(?:kural|talimat|yonerge)\w*")


def _their_content(f: str) -> re.Match[str] | None:
    return _OBLIGED.search(f) or _RULE_WORD.search(f)


@dataclass
class Context:
    """What earlier sentences of the same reply did."""

    referred: bool = False  # a reference was removed
    instructions: bool = False  # a sentence that introduced the instructions was dropped
    asks: bool = False  # the user asked about LAZIS's instructions (:func:`asks_instructions`)
    recital: bool = False  # the rest of the reply is their content: it is dropped


def find_refs(sentence: str, ctx: Context | None = None) -> list[tuple[int, int]]:
    """Spans of internal references in one sentence (indices into ``sentence``)."""
    ctx = ctx or Context()
    f = fold(sentence)
    found = [(m.start(), m.end()) for m in _LABEL_RAW.finditer(sentence)]
    found += [(m.start(), m.end()) for m in _LABEL.finditer(f)]
    quotes = _quoted(sentence)
    cited = _CITE.search(f) is not None
    first = _FIRST.search(f) is not None
    refusal = _REFUSAL.search(f) is not None
    rules = [(_OWNED, False), (_GIVEN, False), (_SYSTEM, True)]
    if ctx.asks:
        rules.append((_ASKED, False))
    for rx, needs_first in rules:
        for m in rx.finditer(f):
            if any(a <= m.start() < b for a, b in quotes):
                continue  # the user's words, quoted
            if _YOURS.search(m.group(0)):
                continue  # "talimatlarınız", "bana verilen talimatlarınız"
            framed = _CLOSE.match(f, m.end()) is not None
            # "… sunduğu hafıza notları dışında erişimim yok" denies everything but the layer.
            framed |= re.match(r"\w*\s+(?:disinda|haric)", f[m.end() :]) is not None
            if needs_first and not (cited and first):
                continue  # "bir dil modeline sistem promptu verilir"
            if refusal and not framed:
                continue  # "… aynen aktarmam mümkün değil", "gizli talimatlarım yok"
            found.append((m.start(), m.end()))
    if ctx.referred:
        found += [(m.start(), m.end()) for m in _BACK.finditer(f)]
    if ctx.instructions and (m := _their_content(f)):
        found.append((0, m.end()))
    return sorted(set(found))


def rewrite_sentence(
    sentence: str, *, frozen: int = 0, ctx: Context | None = None
) -> tuple[str, int]:
    """The sentence without its internal references, and how many were removed. Characters
    before ``frozen`` were already shown and are never changed. ``ctx`` is updated."""
    ctx = ctx if ctx is not None else Context()
    removed = 0
    out = sentence
    listing = _INTRO.search(sentence) is not None or _ITEM.match(sentence) is not None
    if ctx.asks and listing and re.search(r"\w", sentence[frozen:]):
        # Asked for its instructions, the reply enumerates: that is their content.
        ctx.referred = ctx.recital = True
        return _drop(out, frozen), 1
    for _ in range(4):
        refs = [r for r in find_refs(out, ctx) if r[1] > frozen]
        if not refs:
            return out, removed
        removed += 1
        a, b = refs[0]
        a = max(a, frozen)
        if ctx.instructions and _their_content(fold(out)):
            return _drop(out, frozen), removed  # the instructions' content, in its own words
        close = _CLOSE.match(fold(out), b)
        rest = out[close.end() :] if close else ""
        # Asked for them, "Talimatlarıma göre … yapmalıyım" is what they say; unasked, "…
        # göre bunu hafızama almamalıyım" keeps its answer.
        obliged = ctx.asks and _OBLIGED.search(fold(rest)) is not None
        if not re.search(r"\w", rest) or obliged or listing:
            # Not a frame, nothing but the frame, or a frame for what the instructions say
            # ("… doğrultusunda ilkelerim şunlardır:"): the sentence goes, and with it what it
            # introduced.
            ctx.referred = True
            ctx.instructions = ctx.instructions or close is None or obliged or listing
            # What follows an enumeration's introduction, or follows the instructions when the
            # user asked for them, is their content.
            ctx.recital = ctx.recital or listing or (ctx.asks and not _REFUSAL.search(fold(out)))
            return _drop(out, frozen), removed
        ctx.referred = True
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
    """The unshown part of the sentence removed; its line breaks stay. A beginning already shown
    cannot be taken back: it is closed with "…" ("Örneğin, sizin şu…"), not run into the next
    sentence."""
    breaks = re.search(r"\n*$", sentence[frozen:].rstrip(" \t"))
    head = sentence[:frozen]
    cut = "…" if head.strip() and not re.search(r"[.!?:;…\n]\s*$", head) else ""
    return head + cut + (breaks.group(0) if breaks else "")


# Word prefixes that may begin a reference ("sistem" only bare: "sistem notu", not "sistemim").
_RISKY = ("talimat", "yonerge", "prompt", "gelistirici", "gizli", "dahili", "arka", "kisisel",
          "hafiza", "baglam")  # fmt: skip


def _risky_word(w: str) -> bool:
    w = w.strip("'")
    return (
        "_" in w
        or w.startswith(_RISKY)
        or w in ("sistem", "bana", "ic", "bilgi")
        or re.fullmatch(r"istem(?:im\w*|i|in|e|de|den)?", w) is not None
    )


@dataclass
class DisclosureGuard:
    """Streams a reply through the disclosure rules. ``feed`` returns what is safe to show
    now, ``finish`` the rest."""

    released: str = ""
    pending: str = ""
    removed: int = 0
    ctx: Context = field(default_factory=Context)
    _dropping: bool = False  # a dropped sentence was cut at MAX_HOLD: drop on to its end
    _space: str = ""  # whitespace held until text follows (a dropped tail leaves none)

    def feed(self, chunk: str) -> str:
        self.pending += chunk
        return self._release(final=False)

    def finish(self) -> str:
        out = self._release(final=True)
        if self.removed and (self.ctx.recital or not self.released.strip()):
            # The reply was nothing but references, or its rest was the instructions' content.
            piece = FALLBACK
            if self.released.strip() and not self.released.endswith("\n"):
                piece = ("\n\n" if "\n" in self._space else " ") + FALLBACK
            self.released += piece
            out += piece
        return out

    def _risky_at(self, f: str) -> int | None:
        eq = f.find("=")
        for m in _WORD.finditer(f):
            if eq != -1 and eq < m.start():
                return eq
            if _risky_word(m.group(0)):
                return m.start()
        return None if eq == -1 else eq

    def _safe_end(self, f: str, n: int) -> int:
        """``n``, or the start of the sentence that ends there while that sentence has fewer
        than three words: a sentence dropped later must not leave its first word behind
        ("Ben" + " sadece bana iletilen … sistem notlarını …")."""
        ends = [m.end() for m in _SENTENCE_END.finditer(f[:n])]
        start = ends[-1] if ends else 0
        if start == 0 and self.released and not _SENTENCE_END.search(self.released[-2:] + " "):
            return n  # the sentence began in released text already
        if len(_WORD.findall(f[start:n])) < 3:
            return start
        return n

    def _emit(self, n: int) -> str:
        piece, self.pending = self.pending[:n], self.pending[n:]
        return self._add(piece)

    def _add(self, piece: str) -> str:
        if not piece.strip():
            self._space += piece
            return ""
        piece, self._space = self._space + piece, ""
        if self.removed:
            piece = re.sub(r"^(\s*\n)[ \t]+", r"\1", piece)  # no indent after a dropped line
        if self.removed and not self.released.strip():
            piece = piece.lstrip()  # a reply whose first sentence was dropped
        elif self.released.endswith("\n"):
            piece = piece.lstrip(" ")  # a paragraph whose first sentence was dropped
        self.released += piece
        return piece

    def _release(self, *, final: bool) -> str:
        out = ""
        while self.pending:
            if self.ctx.recital:
                self.pending = ""  # the instructions' content: nothing more is shown
                break
            if self._dropping:
                end = _sentence_end(self.pending, final)
                if end is None and len(self.pending) < MAX_HOLD:
                    break
                if end is None:
                    end = self.pending.rfind(" ", 0, MAX_HOLD) + 1 or MAX_HOLD
                else:
                    self._dropping = False
                self.pending = self.pending[end:]
                continue
            f = fold(self.pending)
            # After a reference, every sentence of the reply is checked whole ("Bu yönergeler
            # …", the instructions' content).
            # So is every sentence when the user asked about the instructions.
            risky = 0 if self.ctx.referred or self.ctx.asks else self._risky_at(f)
            if risky is None:
                n = len(self.pending) if final else self._safe_end(f, _before_last_word(f))
                if n == 0:
                    break
                out += self._emit(n)
                continue
            hold_from = self._safe_end(f, _before_last_word(f[:risky]))
            if hold_from > 0:
                out += self._emit(hold_from)
                continue
            end = _sentence_end(self.pending, final)
            cut = end is None
            if end is None:
                if len(self.pending) < MAX_HOLD:
                    break
                end = self.pending.rfind(" ", 0, MAX_HOLD) + 1 or MAX_HOLD
            start = _sentence_start(self.released)
            sentence = self.released[start:] + self.pending[:end]
            frozen = len(self.released) - start
            new, removed = rewrite_sentence(sentence, frozen=frozen, ctx=self.ctx)
            self.removed += removed
            self._dropping = cut and removed > 0 and not re.search(r"\w", new[frozen:])
            self.pending = self.pending[end:]
            out += self._add(new[frozen:])
        return out


def check(text: str, *, asks: bool = False) -> tuple[str, int]:
    """The whole reply at once (the same result as streaming it). ``asks``: the user asked
    about LAZIS's instructions (:func:`asks_instructions`)."""
    guard = DisclosureGuard(ctx=Context(asks=asks))
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
                "kisisel", "hafiza", "baglam", "bana", "bilgi", "istem")  # fmt: skip
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
