"""Truthful memory claims in replies (Phase 7.1, ADR-0017).

LAZIS may say that it saved, deleted or updated something only when that operation really
happened in this turn. The model is told so, but it does not always comply (measured in
Phase 7: 5 of 9 statement replies said "not aldım" while the background learning had not run
yet). This module enforces the rule on the reply text itself, deterministically, from the
**real outcome** of the turn's memory operation — never from what the model wrote, and with
no second model call.

``state_for`` maps the turn's memory request and its outcome to a :class:`ClaimState`.
``ClaimGuard`` sits between the model's stream and everything downstream (the UI, the stored
message, later the voice). It releases text as it arrives but holds back from the first word
that could begin a claim ("kaydettim", "not aldım", "hafızama…", "unutmayacağım") until that
sentence ends, classifies the sentence with a small set of Turkish rules, and rewrites only a
claim the state does not allow. Released text is final: the user never sees a claim that is
taken back later, and the stored reply is exactly the released text.

What counts (folded text, one sentence at a time):

* **claims** — a completed or committed memory act by LAZIS: first person past, present or
  future, or the passive completion ("kaydettim", "not aldım", "hafızama ekledim",
  "kaydedildi", "unutmayacağım", "aklımda tutacağım", "sildim", "güncelledim");
* **not claims** — negation and inability ("kaydetmedim", "kaydedemedim"), ability and
  offers ("kaydedebilirim", "kaydedeyim mi", "kaydederim"), questions ("kaydettim mi?"),
  other persons ("kaydettiniz"), text in quotation marks, statements that nothing is stored
  ("hafızamda bu konuda bir bilgi yok");
* **references to existing records** ("daha önce kaydettiğimiz bilgiye göre", "hafızamdaki
  bilgiye göre", "kaydedilmiş") — allowed when this turn's recall really brought stored
  memory; otherwise they point to the conversation instead ("konuştuğumuz bilgiye göre").

Delete and update verbs ("sildim", "güncelledim") are memory acts only next to a memory word,
with information as their object, or during an explicit memory request — "gereksiz cümleyi
sildim" in an editing task is not.

A memory act need not be the main verb (Phase 9 real-model finding, "Kervan bilgisini
düzelterek bunu esas alıyorum"): a converb ("düzelterek", "kaldırıp", "kaydedince") claims
what the sentence's main verb claims, and adopting a value ("esas alıyorum", "güncel
tutacağım", "bundan sonra dikkate alacağım") claims an update or a save. After the rewrite
the sentence is checked again; a claim that is still there takes the whole rest of the
sentence with it (fail closed).

An unauthorized claim is reworded in place:

* after a statement (learning still pending), "X olduğunu not ettim" → "X olduğunu anladım";
* after a failed request → "kaydedemedim";
* while a deletion waits for confirmation → "henüz silmedim".

The rest of the reply is untouched.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal


class ClaimState(StrEnum):
    NO_MEMORY_ACTION = "no_memory_action"
    AUTO_LEARNING_PENDING = "auto_learning_pending"
    SAVE_SUCCEEDED = "save_succeeded"
    SAVE_FAILED = "save_failed"
    SAVE_PENDING = "save_pending"
    SAVE_CANCELLED = "save_cancelled"  # a waiting save the user called off ("vazgeç")
    DELETE_SUCCEEDED = "delete_succeeded"
    DELETE_FAILED = "delete_failed"
    DELETE_PENDING = "delete_pending"
    UPDATE_SUCCEEDED = "update_succeeded"
    UPDATE_FAILED = "update_failed"


_REQUESTS = (
    "remember",
    "correct",
    "forget",
    "confirm",
    "decline",
    "same",
    "different",
    "secret",
    "choose",
)


_MEMORY_TALK = re.compile(
    r"\b(?:bilgi(?:m|mi|ler|lerim|lerimi|yi|leri|sini|ni)\b|hafiza|kayd|kayit|not al|not et|unut"
    r"|hatirla|aklinda|bildikler)"
)


_HOW = re.compile(
    r"\b(?:nasil|neden|nicin|nedir|ne demek|ne yap(?:mali|ar|iyor)\w*|anlatir mi|aciklar mi"
    r"|ne zaman|hangi durumda)"
)
_DID_YOU = re.compile(r"\w(?:[dt][iu]n|[dt][iu]nuz)\s+m[iu]\b")  # "kaydettin mi?"


def explaining(message: str) -> bool:
    """Whether the user asks in general how something works — not whether it was done."""
    f = fold(message)
    return _HOW.search(f) is not None and _DID_YOU.search(f) is None


def memory_talk(message: str) -> bool:
    """Whether the user's message speaks of the memory or of their information."""
    return _MEMORY_TALK.search(fold(message)) is not None


def state_for(
    intent: str | None, outcome: str | None, *, statement: bool, learning: bool
) -> ClaimState:
    """The state from the real memory operation of this turn (``commands.Outcome.kind``).
    ``statement``: the message tells something; ``learning``: background learning will
    process it (auto-extract on, a trusted model)."""
    if intent in _REQUESTS and outcome and outcome != "none":
        if outcome == "saved":
            return ClaimState.SAVE_SUCCEEDED
        if outcome in ("corrected", "merged", "distinguished"):
            return ClaimState.UPDATE_SUCCEEDED
        if outcome == "forgotten":
            return ClaimState.DELETE_SUCCEEDED
        if outcome == "cancelled":
            return ClaimState.SAVE_CANCELLED
        deleting = intent in ("forget", "confirm", "decline")
        if outcome in ("confirm_needed", "ambiguous"):
            return ClaimState.DELETE_PENDING if deleting else ClaimState.SAVE_PENDING
        if deleting:
            return ClaimState.DELETE_FAILED
        if intent == "correct":
            return ClaimState.UPDATE_FAILED
        return ClaimState.SAVE_FAILED  # failed, refused, nothing, untrusted, secret
    if statement and learning:
        return ClaimState.AUTO_LEARNING_PENDING
    return ClaimState.NO_MEMORY_ACTION


Kind = Literal["save", "delete", "update", "existing"]
_ALLOWED: dict[ClaimState, frozenset[str]] = {
    # A save changed nothing that was there: "güncelledim" is not true (Phase 9).
    ClaimState.SAVE_SUCCEEDED: frozenset({"save"}),
    ClaimState.UPDATE_SUCCEEDED: frozenset({"save", "update"}),
    ClaimState.DELETE_SUCCEEDED: frozenset({"delete"}),
}
# An unauthorized claim, by state and kind, becomes this (otherwise "anladım").
_REPLACEMENT: dict[tuple[ClaimState, str], str] = {
    (ClaimState.SAVE_FAILED, "save"): "kaydedemedim",
    (ClaimState.SAVE_FAILED, "update"): "güncelleyemedim",
    (ClaimState.SAVE_PENDING, "save"): "henüz kaydetmedim",
    (ClaimState.SAVE_CANCELLED, "save"): "kaydetmedim",
    (ClaimState.SAVE_PENDING, "update"): "henüz güncellemedim",
    (ClaimState.UPDATE_FAILED, "save"): "kaydedemedim",
    (ClaimState.UPDATE_FAILED, "update"): "güncelleyemedim",
    (ClaimState.DELETE_FAILED, "delete"): "silmedim",
    (ClaimState.DELETE_PENDING, "delete"): "henüz silmedim",
    (ClaimState.DELETE_FAILED, "save"): "kaydetmedim",
    (ClaimState.DELETE_PENDING, "save"): "henüz kaydetmedim",
    (ClaimState.DELETE_SUCCEEDED, "save"): "kaydetmedim",
    (ClaimState.SAVE_SUCCEEDED, "delete"): "silmedim",
    (ClaimState.SAVE_SUCCEEDED, "update"): "kaydettim",
    (ClaimState.UPDATE_SUCCEEDED, "delete"): "silmedim",
}
ACK = "anladım"
# What the check after the rewording puts in place of a claim that is still there: fixed words,
# not the table above (it is what failed).
_FAIL_CLOSED: dict[ClaimState, str] = {
    ClaimState.SAVE_FAILED: "kaydedemedim",
    ClaimState.UPDATE_FAILED: "güncelleyemedim",
    ClaimState.DELETE_FAILED: "silmedim",
    ClaimState.SAVE_PENDING: "henüz kaydetmedim",
    ClaimState.DELETE_PENDING: "henüz silmedim",
    ClaimState.SAVE_CANCELLED: "kaydetmedim",
}
# The same in the passive voice ("Bilgi kaydedildi." → "Bilgi anlaşıldı.").
_PASSIVE: dict[str, str] = {
    ACK: "anlaşıldı",
    "kaydedemedim": "kaydedilemedi",
    "henüz kaydetmedim": "henüz kaydedilmedi",
    "kaydetmedim": "kaydedilmedi",
    "güncelleyemedim": "güncellenemedi",
    "henüz güncellemedim": "henüz güncellenmedi",
    "silmedim": "silinmedi",
    "henüz silmedim": "henüz silinmedi",
}


@dataclass(frozen=True)
class Policy:
    state: ClaimState
    has_memory: bool = False  # this turn's recall brought stored memory
    memory_turn: bool = False  # an explicit memory request this turn
    # The user's message speaks of the memory or of their information ("Bilgimi güncelle: …")
    # even when no request was recognised: the reply's act verbs are about the memory then.
    memory_talk: bool = False
    # The user asks how the memory works ("Bir bilgiyi nasıl sildirebilirim?"): "hafızamdaki
    # bilgiler" is the store in general and "güncelleyeceğim" a hypothetical (Phase 9: these
    # explanations were reworded into nonsense). A finished act ("kaydettim") is still a claim.
    explaining: bool = False

    def allows(self, kind: str) -> bool:
        if kind == "existing":
            return self.has_memory
        return kind in _ALLOWED.get(self.state, frozenset())


@dataclass(frozen=True)
class Rewrite:
    kind: str
    state: str
    original: str  # the claim's words (kept in memory for tests; never logged)
    replacement: str


# ----- folding (one character for one character, Turkish casing) ---------------------------
_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a",
                       "î": "i", "û": "u", "’": "'", "‘": "'", "`": "'", "´": "'"})  # fmt: skip


def fold(text: str) -> str:
    """Lower-case and fold; indices into the result are indices into ``text``."""
    out: list[str] = []
    for ch in text:
        low = "i" if ch == "İ" else "ı" if ch == "I" else ch.lower()
        out.append(low if len(low) == 1 else ch)
    return "".join(out).translate(_FOLD)


# ----- verbs and endings (folded) ----------------------------------------------------------
# Memory context words: they make an ordinary verb a memory act ("hafızama ekledim").
_CONTEXT = (
    r"(?:hafiza(?:m|mi|ma|mda|mdan|mdaki|miza|mizda|mizdaki)|akli(?:m|ma|mda)"
    r"|notlarim(?:a|da|in)?|kayitlarim(?:a|da|in)?|bilgilerime|listeme|ajandama|defterime|takvimime"
    r"|hafizamin|aklimin|bilgilerim(?:in)?|listemin)"
)
_CONTEXT_RE = re.compile(r"\b" + _CONTEXT + r"\b")
_SAVE_RE = re.compile(
    r"\b(?:kayded|kaydet|kayit alti[a-z]* al|kayda gecir|kayda al|(?:bir )?kayit (?:olustur|ac)"
    r"|kayd(?:i|im|imi|ini|inizi|larini|larinizi) (?:al|tut|olustur)"
    r"|kayitlar(?:i|im|imi|ini|inizi) (?:al|tut|olustur)"
    # Every possessive and accusative form ("notumu aldım", Phase 7.2 real-model finding).
    r"|not(?:u|um(?:u|uz|uzu)?|un(?:u|uz|uzu)?|lar(?:i|im|imi|imiz|imizi|in|ini|iniz|inizi)?)?"
    r" (?:al|ed|et|tut))"
)
# A save claim with a note/record noun as its object keeps the sentence's grammar when it is
# reworded: "Ahmet'in kaydını aldım" → "Ahmet'in bilgisini anladım" (not "Ahmet'in anladım").
_NOUN_OBJECT = re.compile(r"(?:bir )?(?:not|kayd|kayit)(u|unu|ini|lari|larini)? ")
_NOUN_SUBSTITUTE = {"u": "bilgiyi", "unu": "bilgisini", "ini": "bilgisini", "lari": "bilgileri",
                    "larini": "bilgilerini", None: ""}  # fmt: skip
_CTX_VERB = r"(?:ekle|al|yaz|tut|kayded|kaydet|isle|sakla)"
_DISTANT_VERB = re.compile(r"\b(?:ekle|yaz|kayded|kaydet|isle|sakla|not (?:al|ed|et))")
_ADJACENT = ("", "bu", "bunu", "bu bilgiyi", "onu")
_POSTPOSITION = re.compile(r"\s+(?:bir\s+)?(?:arasina|icine|kosesine|listesine|ustune)\b")
_DELETE_RE = re.compile(r"\b(?:sil|kaldir|cikar)")
_UPDATE_RE = re.compile(r"\b(?:guncell|duzelt|degistir|birlestir)")
# "Bilgiyi güncelledim", "iş yeri bilginizi sildim": information as the object makes these
# verbs memory acts too (Phase 9 real-model finding: "Bilgiyi güncelledim" after a conflict).
_INFO_OBJECT = re.compile(
    r"\bbilgi(?:yi|leri|lerini|lerinizi|nizi|sini|mi|lerimi)?\s+"
    r"(?:sil|kaldir|cikar|guncell|duzelt|degistir|birlestir)"
)
# Information as an object anywhere in the sentence ("Bilgilerinizi az önce düzelttim"); the
# bare "bilgi" ("bilgi vermek") is not one.
_INFO_NOUN = re.compile(r"\bbilgi(?:yi|leri|lerini|lerinizi|nizi|sini|mi|lerimi)\b")
# Adopting a value as what is true from now on: an update ("esas alıyorum") or a save ("güncel
# tutacağım"). Taking something into account is one only beyond this conversation ("bundan
# sonra dikkate alacağım"; "bu konuşmada dikkate alacağım" is true).
_ADOPT_RE = re.compile(
    r"\b(?:(esas|temel|baz|referans) al|guncel tut|kalici olarak (?:tut|sakl|kullan|kayded|kaydet))"
)
_HEED_RE = re.compile(r"\b(?:dikkate al|goz onunde (?:bulundur|tut))")
_LASTING = re.compile(r"\b(?:bundan (?:boyle|sonra|itibaren)|artik|ileride|kalici|her zaman)\b")
_COMMIT_RE = re.compile(r"\b(?:unut|hatirla)")
_OGREN_RE = re.compile(r"\bogren")

_V = "[aeiu]"
_NEGATED = re.compile(
    rf"(?:{_V}?m[ea]|(?:il|in|l|n)m[ea])"
)  # kaydetme(di), kaydedeme, kaydedilmedi
_ABILITY = re.compile(rf"{_V}?y?[ea]bil")  # kaydedebilirim
# Converbs, also passive: "düzelterek", "kaldırıp", "güncelleyip", "kaydedince", "sildikten",
# "silinerek". They claim what the main verb claims.
_CONVERB = re.compile(
    r"(?:[ae]?(?:il|in|l|n))?(?:[ae]?y?[ae]r[ae]k|[ae]?y?[iu]p|[ae]?y?[iu]nc[ae]|[ae]?[dt][iu]kt[ae]n)\b"
)
# The main verb: a first-person act, finished, ongoing or committed ("alıyorum", "kullanacağım",
# "tamamladım") — not negated ("kullanmadım", "kaydedemedim").
_MAIN_DONE = re.compile(r"(?:[dt][iu][mk]|yor(?:um|uz)|y?[ae]c[ae]g(?:im|iz)|m[ae]kt[ae]y[iu]m)$")
_MAIN_NOT = re.compile(r"m[ae]d[iu]|m[ae]y[ae]c[ae]g|m[iu]yor|m[ae]kt[ae]n|y?[ae]bil")
_FILLER = frozenset({"efendim", "simdilik", "artik", "de", "da", "hemen", "zaten", "boylece"})
# First-person participles and passive forms speak of an existing record ("kaydettiğim(iz)",
# "kaydedilmiş", "kaydedilen"); "Ahmet not etmiş" (someone else, evidential) does not.
_EXISTING = re.compile(
    rf"(?:{_V}?(?:t|d)[iu]g(?:im|imiz|um|umuz)|(?:il|in|l|n)mis|(?:il|in|l|n)en\b)"
)
_PASSIVE_DONE = re.compile(
    r"[ae]?(?:il|in|l|n)d[iu](?:r)?\b|[ae]?(?:il|in|l|n)mistir\b"
)  # kaydedildi, eklendi, güncellendi
_DONE = re.compile(
    rf"{_V}?(?:t|d)(?:im|um|ik|uk)\b"  # kaydettim, aldım, sildik, güncelledim
    rf"|{_V}?yor(?:um|uz)\b"  # kaydediyorum, güncelliyorum
    rf"|{_V}?y?[ea]c[ea]g(?:im|iz)\b"  # kaydedeceğim, tutacağım
)
_NOTHING_STORED = re.compile(
    r"\b(?:yok|yoktur|bulunmuyor|bulunmamakta|degil|bilmiyorum|hatirlamiyorum)\b"
)
_WORD_CHARS = re.compile(r"[0-9a-z']")


@dataclass(frozen=True)
class _Claim:
    start: int  # from the memory context word, if any
    end: int
    verb_start: int
    kind: str
    passive: bool = False  # "kaydedildi": the reworded form is passive too
    # A storage word further back in the sentence ("Not defterime X'i ekledim"): its span, so
    # "anladım" can drop it and keep what stands between.
    ctx_span: tuple[int, int] | None = None


def _word_end(f: str, i: int) -> int:
    while i < len(f) and _WORD_CHARS.match(f[i]):
        i += 1
    return i


def _verdict(rest: str) -> Literal["done", "passive", "existing", "converb", "not"]:
    """What a verb's ending says (``rest``: folded text from the stem's end to the word end,
    plus one character)."""
    if _NEGATED.match(rest) or _ABILITY.match(rest):
        return "not"
    if _EXISTING.match(rest):
        return "existing"
    if _PASSIVE_DONE.match(rest):
        return "passive"
    if _DONE.match(rest):
        return "done"
    if _CONVERB.match(rest):
        return "converb"
    return "not"  # offers, conditions, other persons, unrelated words


def _main_verb_end(f: str, end: int) -> int | None:
    """Where the main verb after a converb ends, if it is a first-person act (the sentence's
    last word but fillers: Turkish puts the verb last). None for a question or a negation."""
    clause = re.match(r"[^.!?\n;:]*", f[end:])
    words = list(re.finditer(r"[a-z0-9']+", clause.group(0) if clause else ""))
    while words and words[-1].group(0) in _FILLER:
        words.pop()
    if not words:
        return None
    w = words[-1].group(0)
    if _MAIN_DONE.search(w) and not _MAIN_NOT.search(w):
        return end + words[-1].end()
    return None


def _quoted(text: str) -> list[tuple[int, int]]:
    rx = r'"[^"]*"|“[^”]*”|«[^»]*»|‘[^’]*’|(?:(?<=\s)|^)\'[^\']+\'(?=[\s.,;:!?)]|$)'
    return [(m.start(), m.end()) for m in re.finditer(rx, text)]


def _context_before(f: str, i: int) -> int | None:
    m = re.search(_CONTEXT + r"\s+(?:bu bilgiyi\s+|bunu\s+)?$", f[:i])
    return m.start() if m else None


def find_claims(sentence: str, policy: Policy) -> list[_Claim]:
    """Memory-act claims and references in one sentence (spans index into ``sentence``)."""
    f = fold(sentence)
    quotes = _quoted(sentence)
    found: list[_Claim] = []

    def mentioned(end: int) -> bool:
        """The phrase is talked about, not said: "not aldım gibi", "kaydettim diye"."""
        return re.match(r"\s+(?:gibi|diye|demek|deme|dememe)\b", f[end:]) is not None

    def quoted(i: int) -> bool:
        return any(a <= i < b for a, b in quotes)

    def verb(
        start: int,
        stem_end: int,
        kind: str,
        ctx: int | None = None,
        ctx_span: tuple[int, int] | None = None,
    ) -> None:
        if quoted(start) or any(c.verb_start == start for c in found):
            return
        end = _word_end(f, stem_end)
        if re.match(r"\s+m[iu]\b", f[end : end + 4]) or mentioned(end):  # "kaydettim mi?"
            return
        verdict = _verdict(f[stem_end:end] + f[end : end + 1])
        perfect = re.match(r"\s+ol(?:dum|duk)\b", f[end:])
        if verdict == "not" and perfect and re.fullmatch(r"[ae]?m[iu]s", f[stem_end:end]):
            # "not etmiş oldum", "kaydetmiş oldum": the perfect tense, a completed act
            # (Phase 7.2 real-model finding).
            verdict, end = "done", end + perfect.end()
        if verdict == "converb":
            main = _main_verb_end(f, end)
            if main is None:
                return  # "düzelterek tekrar sorayım mı?", "silmeden önce"
            verdict, end = "done", main
        if verdict == "not":
            return
        if verdict == "existing" and re.search(
            r"[dt][iu]g(?:im|imiz|um|umuz)(?:d[ae]|ten|tan)$", f[start:end]
        ):
            return  # "kaydettiğimde": when, not a record that exists
        if policy.explaining and (
            verdict == "existing" or re.search(r"(?:c[ae]g(?:im|iz)|yor(?:um|uz))$", f[start:end])
        ):
            return  # how it works, not what happened
        if verdict == "existing":
            if _NOTHING_STORED.search(f[end:]):
                return  # "kaydettiğimiz bir bilgi yok": saying nothing is stored is true
            kind = "existing"
        found.append(
            _Claim(
                ctx if ctx is not None else start, end, start, kind, verdict == "passive", ctx_span
            )
        )

    # A save verb later in the sentence than a storage word in the dative ("Not defterime
    # Ahmet'in doğum gününü ekledim", "Hafızama bu konuşmadan iki bilgi yazdım").
    for m in _CONTEXT_RE.finditer(f):
        word, place_end = m.group(0), m.end()
        # "kayıtlarım arasına", "hafızamın bir köşesine": a storage place with a postposition.
        post = _POSTPOSITION.match(f, m.end())
        if post is not None:
            place_end = post.end()
        elif not word.endswith(("a", "e")) or word.endswith(("da", "de")):
            continue
        if quoted(m.start()):
            continue
        for v in _DISTANT_VERB.finditer(f, place_end):
            if post is None and f[place_end : v.start()].strip() in _ADJACENT:
                break  # adjacent: the ordinary rules below handle it
            span_start = m.start() - 4 if f[: m.start()].endswith("not ") else m.start()
            verb(v.start(), v.end(), "save", span_start, (span_start, place_end))
            break

    for m in _SAVE_RE.finditer(f):
        verb(m.start(), m.end(), "save", _context_before(f, m.start()))
    for m in _CONTEXT_RE.finditer(f):
        nxt = re.match(r"\s+(?:(?:bu|bunu|bu bilgiyi|onu)\s+)?(" + _CTX_VERB + ")", f[m.end() :])
        if nxt is not None:
            start = m.end() + nxt.start(1)
            verb(start, start + len(nxt.group(1)), "save", m.start())
        elif (
            m.group(0).endswith(("da", "daki"))
            and not quoted(m.start())
            and not _NOTHING_STORED.search(f[m.end() :])
        ):
            # "hafızamdaki bilgiye göre", "hafızamda … var": a reference to stored records.
            if not policy.explaining:
                found.append(_Claim(m.start(), m.end(), m.start(), "existing"))
    for m in _COMMIT_RE.finditer(f):
        end = _word_end(f, m.end())
        if quoted(m.start()) or mentioned(end):
            continue
        rest = f[m.end() : end]
        ctx = _context_before(f, m.start())
        if m.group(0) == "unut":
            if re.fullmatch(r"m[ae]y[ae]c[ae]g(?:im|iz)|mam|mayiz", rest):  # "unutmayacağım"
                found.append(_Claim(ctx if ctx is not None else m.start(), end, m.start(), "save"))
            elif re.fullmatch(r"(?:t|d)(?:um|uk)", rest) and (
                policy.memory_turn or ctx is not None
            ):
                found.append(
                    _Claim(ctx if ctx is not None else m.start(), end, m.start(), "delete")
                )
        elif re.fullmatch(r"y[ae]c[ae]g(?:im|iz)|rim|riz", rest):  # "hatırlayacağım"
            found.append(_Claim(ctx if ctx is not None else m.start(), end, m.start(), "save"))
    for m in _OGREN_RE.finditer(f):
        end = _word_end(f, m.end())
        if (
            not quoted(m.start())
            and not mentioned(end)
            and re.fullmatch(r"(?:d|t)(?:im|ik)", f[m.end() : end])
        ):
            found.append(_Claim(m.start(), end, m.start(), "save"))
    memory_words = (
        policy.memory_turn
        or policy.memory_talk
        or _CONTEXT_RE.search(f)
        or re.search(r"\bkay(?:it|d)", f)
        or _INFO_OBJECT.search(f)
        or _INFO_NOUN.search(f)
    )
    if memory_words:
        for rx, kind in ((_DELETE_RE, "delete"), (_UPDATE_RE, "update")):
            for m in rx.finditer(f):
                verb(m.start(), m.end(), kind, _context_before(f, m.start()))
    if memory_words or policy.state is not ClaimState.NO_MEMORY_ACTION:
        # After the user told something, adopting a value is about what they told.
        for m in _ADOPT_RE.finditer(f):
            kind = "update" if m.group(1) else "save"
            verb(m.start(), m.end(), kind, _context_before(f, m.start()))
    lasting = _LASTING.search(f) or _CONTEXT_RE.search(f) or _INFO_NOUN.search(f)
    if lasting:
        # "Bundan sonra Atlas'ı esas alacağım", "… dikkate alacağım": a commitment that needs
        # a memory.
        for rx in (_ADOPT_RE, _HEED_RE):
            for m in rx.finditer(f):
                kind = "update" if rx is _ADOPT_RE and m.group(1) else "save"
                verb(m.start(), m.end(), kind, _context_before(f, m.start()))
    found.sort(key=lambda c: (c.start, -c.end))
    merged: list[_Claim] = []
    for c in found:
        if merged and c.start < merged[-1].end:
            continue
        merged.append(c)
    return merged


_ACK_RE = re.compile(r"\b(?:anladim|anliyorum|anlasildi|tamam)\b")


def rewrite_sentence(
    sentence: str, policy: Policy, *, frozen: int = 0
) -> tuple[str, list[Rewrite]]:
    """The sentence with every unauthorized claim reworded. Characters before ``frozen`` were
    already shown and are never changed."""
    claims = [
        c for c in find_claims(sentence, policy) if c.start >= frozen and not policy.allows(c.kind)
    ]
    out = sentence
    rewrites: list[Rewrite] = []
    for c in reversed(claims):
        if c.kind == "existing":
            replacement = _existing_replacement(fold(out[c.start : c.end]))
            if replacement is None:
                continue
            start = c.start
        else:
            replacement = _REPLACEMENT.get((policy.state, c.kind), ACK)
            if c.passive:
                replacement = _PASSIVE.get(replacement, "anlaşıldı")
            # "hafızama kaydedemedim" keeps the context word; "anladım" replaces it too.
            start = c.verb_start if replacement not in (ACK, "anlaşıldı") else c.start
            if c.ctx_span is not None:
                # Replace the verb; "anladım" also drops the storage word ("Not defterime X'i
                # ekledim" → "X'i anladım"), a failure keeps it ("Not defterime X'i kaydedemedim").
                a, b = c.ctx_span
                verb_repl = replacement
                if _at_sentence_start(out, c.verb_start):
                    verb_repl = verb_repl[:1].upper() + verb_repl[1:]
                rewrites.append(Rewrite(c.kind, policy.state.value, out[c.verb_start : c.end],
                                        verb_repl))  # fmt: skip
                out = out[: c.verb_start] + verb_repl + out[c.end :]
                if replacement in (ACK, "anlaşıldı"):
                    gap = re.match(r"\s*", out[b:])
                    tail = out[b + (gap.end() if gap else 0) :]
                    if _at_sentence_start(out, a):
                        tail = tail[:1].upper() + tail[1:]
                    out = out[:a] + tail
                continue
            if replacement == ACK and _ACK_RE.search(fold(out[: c.start])):
                dropped = _drop(out, c, frozen)
                if dropped is not None:
                    rewrites.append(Rewrite(c.kind, policy.state.value, out[c.start : c.end], ""))
                    out = dropped
                    continue
            noun = _NOUN_OBJECT.match(fold(out[c.verb_start : c.end]))
            if (
                noun is not None
                and c.kind == "save"
                and (noun.group(1) or noun.group(0).startswith("bir "))
            ):
                start = c.verb_start
                substitute = _NOUN_SUBSTITUTE[noun.group(1)]
                if noun.group(0).startswith("bir "):  # "bir kayıt oluşturdum" → "bunu anladım"
                    substitute = "bunu"
                if _object_before(out, start):  # "bunu" is already there
                    substitute = ""
                replacement = f"{substitute} {replacement}".strip()
        if _at_sentence_start(out, start):
            replacement = replacement[:1].upper() + replacement[1:]
        rewrites.append(Rewrite(c.kind, policy.state.value, out[start : c.end], replacement))
        out = out[:start] + replacement + out[c.end :]
    rewrites.reverse()
    left = [
        c
        for c in find_claims(out, policy)
        if c.start >= frozen and c.kind != "existing" and not policy.allows(c.kind)
    ]
    if left:
        # Fail closed: a claim the rewording did not remove takes the rest of the sentence.
        c = left[0]
        replacement = _FAIL_CLOSED.get(policy.state, ACK)
        if _at_sentence_start(out, c.start):
            replacement = replacement[:1].upper() + replacement[1:]
        tail = re.search(r"[.!?\n:;\s]*$", out)
        end = tail.start() if tail else len(out)
        rewrites.append(Rewrite(c.kind, policy.state.value, out[c.start : end], replacement))
        out = out[: c.start] + replacement + out[end:]
    return out, rewrites


_OBJECT = re.compile(
    r"\b(?:bunu|bu bilgiyi|bunlari|onu"
    r"|(?:[a-z0-9']+ )?bilgi(?:yi|leri|sini|lerini|nizi|lerinizi))\s+$"
)


def _object_before(out: str, i: int) -> bool:
    """An object already stands before the claim ("bunu notunu aldım" is not reworded with
    a second one)."""
    return _OBJECT.search(fold(out[:i])) is not None


def _drop(out: str, c: _Claim, frozen: int) -> str | None:
    """The sentence without a claim that repeats an acknowledgement ("Anladım ve not aldım."
    → "Anladım."), with its object pronoun and one connector; None if a connector that would
    have to go was already shown (the claim is reworded instead)."""
    obj = _OBJECT.search(fold(out[: c.start]))
    first = obj.start() if obj is not None and obj.start() >= frozen else c.start
    after = re.match(r"\s+ve\b\s*", out[c.end :])
    if after is not None:  # "…, bunu kaydettim ve X" → "…, X"
        return out[:first] + out[c.end + after.end() :]
    # Only a claim that is its own clause: "…, İzmir'de olduğunuzu not ettim" would leave its
    # object behind ("…, İzmir'de olduğunuzu.") and is reworded instead.
    before = re.search(r"(?:\s*,\s*|\s+ve\s+)$", out[:first])
    if before is None or before.start() < frozen:
        return None
    return out[: before.start()] + out[c.end :]


def _existing_replacement(f: str) -> str | None:
    """A reference to records the recall did not bring: point to the conversation."""
    if f.startswith(("hafizamdaki", "hafizamizdaki")):
        return "konuşmamızdaki"
    if f.startswith(("hafizamda", "hafizamizda", "aklimda")):
        return "konuşmamızda"
    if re.search(r"mis$", f):
        return "konuşmamızda geçmiş"
    if re.search(r"(?:t|d)[iu]g", f):
        return "konuştuğumuz"
    if re.search(r"en$", f):
        return "konuşmamızda geçen"
    return None


def _at_sentence_start(text: str, i: int) -> bool:
    j = i - 1
    while j >= 0 and text[j] in " \t\"'“«(*":
        j -= 1
    return j < 0 or text[j] in ".!?\n:"


def check(text: str, policy: Policy) -> tuple[str, list[Rewrite]]:
    """The whole reply at once (the same result as streaming it through :class:`ClaimGuard`)."""
    guard = ClaimGuard(policy)
    out = guard.feed(text) + guard.finish()
    return out, guard.rewrites


# ----- streaming ---------------------------------------------------------------------------
# Words that may begin a claim or a reference (folded prefixes). The last word of what has
# arrived is always held too: it may be incomplete ("Kay" + "dettim") or the connector of a
# claim that follows ("ve" + "not aldım").
_RISKY = ("kayd", "kayit", "not", "hafiza", "akli", "notlar", "unut", "hatirla", "ogren",
          "bilgilerim", "listem", "ajandam", "defterim", "takvimim")  # fmt: skip
# Act verbs are held in every turn: whether "düzelterek" is a claim depends on the words after
# it ("… bilgisini … esas alıyorum"), and shown text is never taken back.
_RISKY_ACT = ("sil", "kaldir", "cikar", "guncell", "duzelt", "degistir", "birlestir")
# Adopting words are risky only before their verb ("esas al…", "güncel tut…"): "temel olarak",
# "güncel bilgiler" flow on. The next word may not have arrived yet: then it is held.
_RISKY_ADOPT = {"esas": "al", "temel": "al", "baz": "al", "referans": "al", "dikkate": "al",
                "guncel": "tut", "kalici": "olarak"}  # fmt: skip
# Information as an object ("Bilgiyi güncelledim"): whole words, so "bilgisayar" flows on.
_RISKY_INFO = re.compile(r"bilgi(?:yi|leri|lerini|lerinizi|nizi|sini|mi|lerimi)?")
_SENTENCE_END = re.compile(r"[.!?\n]+(?=\s|$)|[:;](?=\s)")
MAX_HOLD = 240  # characters held without a sentence end before deciding at a word boundary


@dataclass
class ClaimGuard:
    """Streams a reply through the claim rules. ``feed`` returns what is safe to show now,
    ``finish`` the rest; together they are the reply that is shown, stored and spoken."""

    policy: Policy
    released: str = ""  # shown, final
    pending: str = ""  # received, not shown yet
    rewrites: list[Rewrite] = field(default_factory=list[Rewrite])

    def feed(self, chunk: str, *, whole_words: bool = False) -> str:
        """``whole_words``: the chunk ends where a word ends (text another guard released), so
        its last word is complete and need not be held — only a risky one is."""
        self.pending += chunk
        return self._release(final=False, whole=whole_words)

    def finish(self) -> str:
        return self._release(final=True)

    def _risky_at(self, f: str) -> int | None:
        words = list(re.finditer(r"[a-z0-9']+", f))
        for i, m in enumerate(words):
            if _risky_word(m.group(0), words[i + 1].group(0) if i + 1 < len(words) else None):
                return m.start()
        return None

    def _last_risky(self, f: str, end: int) -> int:
        """The start of the last risky word in ``f[:end]`` after the first word (0 if none)."""
        last = 0
        words = list(re.finditer(r"[a-z0-9']+", f[:end]))
        for i, m in enumerate(words):
            nxt = words[i + 1].group(0) if i + 1 < len(words) else None
            if m.start() > 0 and _risky_word(m.group(0), nxt):
                last = m.start()
        return last

    def _emit(self, n: int) -> str:
        piece, self.pending = self.pending[:n], self.pending[n:]
        self.released += piece
        return piece

    def _release(self, *, final: bool, whole: bool = False) -> str:
        out = ""
        while self.pending:
            f = fold(self.pending)
            risky = self._risky_at(f)
            if risky is None:
                n = len(self.pending) if final or whole else _before_last_word(f)
                if n == 0:
                    break
                out += self._emit(n)
                continue
            hold_from = _before_last_word(f[:risky])
            if hold_from > 0:  # release up to the word before the risky one
                out += self._emit(hold_from)
                continue
            end = _sentence_end(self.pending, final, at_chunk_end=whole)
            if end is None:
                if len(self.pending) < MAX_HOLD:
                    break
                end = self.pending.rfind(" ", 0, MAX_HOLD) + 1 or MAX_HOLD
                # A claim must not straddle the cut: the last risky word starts the next hold.
                end = self._last_risky(f, end) or end
            start = _sentence_start(self.released)
            sentence = self.released[start:] + self.pending[:end]
            frozen = len(self.released) - start
            new, rewrites = rewrite_sentence(sentence, self.policy, frozen=frozen)
            self.rewrites += rewrites
            piece = new[frozen:]
            self.pending = self.pending[end:]
            self.released += piece
            out += piece
        return out


def _risky_word(w: str, nxt: str | None = None) -> bool:
    w = w.strip("'")
    if w in _RISKY_ADOPT:
        return nxt is None or nxt.startswith(_RISKY_ADOPT[w])
    return w.startswith(_RISKY) or w.startswith(_RISKY_ACT) or bool(_RISKY_INFO.fullmatch(w))


def _before_last_word(f: str) -> int:
    """Where the held tail begins: the last word with the space before it — and the word
    before that too when the last word may still become a risky one ("ve n" + "ot aldım":
    the connector must stay held with it)."""
    words = list(re.finditer(r"[a-z0-9']+", f))
    if not words:
        return 0
    keep = words[-1]
    if len(words) > 1 and any(
        r.startswith(keep.group(0)) for r in (*_RISKY, *_RISKY_ACT, *_RISKY_ADOPT)
    ):
        keep = words[-2]
    m = re.search(r"\s*$", f[: keep.start()])
    return m.start() if m is not None else keep.start()


def _sentence_end(text: str, final: bool, *, at_chunk_end: bool = False) -> int | None:
    """``at_chunk_end``: a period at the very end is final (the text another guard released
    ends a sentence only where whitespace followed it)."""
    for m in _SENTENCE_END.finditer(text):
        if m.end() < len(text) or final or at_chunk_end:
            return m.end()
        # A period at the very end of what arrived may still continue ("3." + "5").
    return len(text) if final else None


def _sentence_start(text: str) -> int:
    best = 0
    for m in _SENTENCE_END.finditer(text):
        best = m.end()
    return best
