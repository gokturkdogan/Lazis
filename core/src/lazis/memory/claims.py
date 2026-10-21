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

Delete and update verbs ("sildim", "güncelledim") are memory acts only next to a memory word
or during an explicit memory request — "gereksiz cümleyi sildim" in an editing task is not.

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
    ClaimState.SAVE_SUCCEEDED: frozenset({"save", "update"}),
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
    (ClaimState.UPDATE_SUCCEEDED, "delete"): "silmedim",
}
ACK = "anladım"
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
    r"|notlarim(?:a|da)?|kayitlarim(?:a|da)?|bilgilerime|listeme|ajandama|defterime|takvimime)"
)
_CONTEXT_RE = re.compile(r"\b" + _CONTEXT + r"\b")
_SAVE_RE = re.compile(
    r"\b(?:kayded|kaydet|kayit alti[a-z]* al|kayda gecir|kayda al|(?:bir )?kayit (?:olustur|ac)"
    r"|kayd(?:ini|inizi|larini|larinizi) (?:al|tut|olustur)"
    r"|not(?:u|unu|unuzu|lari|larini|larinizi)? (?:al|ed|et|tut))"
)
# A save claim with a note/record noun as its object keeps the sentence's grammar when it is
# reworded: "Ahmet'in kaydını aldım" → "Ahmet'in bilgisini anladım" (not "Ahmet'in anladım").
_NOUN_OBJECT = re.compile(r"(?:bir )?(?:not|kayd|kayit)(u|unu|ini|lari|larini)? ")
_NOUN_SUBSTITUTE = {"u": "bilgiyi", "unu": "bilgisini", "ini": "bilgisini", "lari": "bilgileri",
                    "larini": "bilgilerini", None: ""}  # fmt: skip
_CTX_VERB = r"(?:ekle|al|yaz|tut|kayded|kaydet|isle|sakla)"
_DISTANT_VERB = re.compile(r"\b(?:ekle|yaz|kayded|kaydet|isle|sakla|not (?:al|ed|et))")
_ADJACENT = ("", "bu", "bunu", "bu bilgiyi", "onu")
_DELETE_RE = re.compile(r"\b(?:sil|kaldir|cikar)")
_UPDATE_RE = re.compile(r"\b(?:guncell|duzelt|degistir|birlestir)")
_COMMIT_RE = re.compile(r"\b(?:unut|hatirla)")
_OGREN_RE = re.compile(r"\bogren")

_V = "[aeiu]"
_NEGATED = re.compile(
    rf"(?:{_V}?m[ea]|(?:il|in|l|n)m[ea])"
)  # kaydetme(di), kaydedeme, kaydedilmedi
_ABILITY = re.compile(rf"{_V}?y?[ea]bil")  # kaydedebilirim
# First-person participles and passive forms speak of an existing record ("kaydettiğim(iz)",
# "kaydedilmiş", "kaydedilen"); "Ahmet not etmiş" (someone else, evidential) does not.
_EXISTING = re.compile(
    rf"(?:{_V}?(?:t|d)[iu]g(?:im|imiz|um|umuz)|(?:il|in|l|n)mis|(?:il|in|l|n)en\b)"
)
_PASSIVE_DONE = re.compile(
    r"(?:il|in|l|n)d[iu](?:r)?\b|(?:il|in|l|n)mistir\b"
)  # kaydedildi, eklendi
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


def _verdict(rest: str) -> Literal["done", "passive", "existing", "not"]:
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
    return "not"  # offers, conditions, other persons, unrelated words


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
        if verdict == "not":
            return
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
        word = m.group(0)
        if not word.endswith(("a", "e")) or word.endswith(("da", "de")) or quoted(m.start()):
            continue
        for v in _DISTANT_VERB.finditer(f, m.end()):
            if f[m.end() : v.start()].strip() in _ADJACENT:
                break  # adjacent: the ordinary rules below handle it
            span_start = m.start() - 4 if f[: m.start()].endswith("not ") else m.start()
            verb(v.start(), v.end(), "save", span_start, (span_start, m.end()))
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
    if policy.memory_turn or _CONTEXT_RE.search(f) or re.search(r"\bkay(?:it|d)", f):
        for rx, kind in ((_DELETE_RE, "delete"), (_UPDATE_RE, "update")):
            for m in rx.finditer(f):
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
    return out, list(reversed(rewrites))


_OBJECT = re.compile(r"\b(?:bunu|bu bilgiyi|bunlari|onu)\s+$")


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
    before = re.search(r"(?:\s*,\s*|\s+ve\s+|\s+)$", out[:first])
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
          "bilgilerime", "listeme", "ajandama", "defterime", "takvimime")  # fmt: skip
_RISKY_ACT = ("sil", "kaldir", "cikar", "guncell", "duzelt", "degistir", "birlestir")
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

    def feed(self, chunk: str) -> str:
        self.pending += chunk
        return self._release(final=False)

    def finish(self) -> str:
        return self._release(final=True)

    def _risky_at(self, f: str) -> int | None:
        acts = self.policy.memory_turn or _CONTEXT_RE.search(fold(self.released[-200:]))
        for m in re.finditer(r"[a-z0-9']+", f):
            w = m.group(0)
            if w.startswith(_RISKY) or (acts and w.startswith(_RISKY_ACT)):
                return m.start()
        return None

    def _last_risky(self, f: str, end: int) -> int:
        """The start of the last risky word in ``f[:end]`` after the first word (0 if none)."""
        acts = self.policy.memory_turn or _CONTEXT_RE.search(fold(self.released[-200:]))
        last = 0
        for m in re.finditer(r"[a-z0-9']+", f[:end]):
            w = m.group(0)
            if m.start() > 0 and (w.startswith(_RISKY) or (acts and w.startswith(_RISKY_ACT))):
                last = m.start()
        return last

    def _emit(self, n: int) -> str:
        piece, self.pending = self.pending[:n], self.pending[n:]
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
            if hold_from > 0:  # release up to the word before the risky one
                out += self._emit(hold_from)
                continue
            end = _sentence_end(self.pending, final)
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


def _before_last_word(f: str) -> int:
    """Where the held tail begins: the last word with the space before it — and the word
    before that too when the last word may still become a risky one ("ve n" + "ot aldım":
    the connector must stay held with it)."""
    words = list(re.finditer(r"[a-z0-9']+", f))
    if not words:
        return 0
    keep = words[-1]
    if len(words) > 1 and any(r.startswith(keep.group(0)) for r in _RISKY + _RISKY_ACT):
        keep = words[-2]
    m = re.search(r"\s*$", f[: keep.start()])
    return m.start() if m is not None else keep.start()


def _sentence_end(text: str, final: bool) -> int | None:
    for m in _SENTENCE_END.finditer(text):
        if m.end() < len(text) or final:
            return m.end()
        # A period at the very end of what arrived may still continue ("3." + "5").
    return len(text) if final else None


def _sentence_start(text: str) -> int:
    best = 0
    for m in _SENTENCE_END.finditer(text):
        best = m.end()
    return best
