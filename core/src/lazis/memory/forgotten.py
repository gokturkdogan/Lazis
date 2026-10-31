"""What the user asked LAZIS to forget, as a check on text (Phase 10A, ADR-0021).

Forgetting deletes the records and keeps only keyed fingerprints (HMAC, never text) so that
nothing is learned again (:func:`lazis.memory.service._forget`). The words are still in the
chat history and in conversation summaries, and the model reads them there: "Mehmet bu
kişilerden hangisinin kuzeniydi?" right after "Ahmet ile Mehmet arasındaki ilişkiyi unut"
(Phase 7 sessions, 6.ask). This index tells whether a sentence speaks of something forgotten,
still without any forgotten text:

* **a relationship** — the sentence names a stored person and a relation word, the other
  end is named in the sentence, in the user's message or is the user ("kuzeniniz"), and
  their pair, or their relationship of that type, was forgotten ("Mehmet bu kişilerden
  hangisinin kuzeniydi?" after "Mehmet, Ahmet'in neyi oluyor?");
* **a value** — a span of the sentence is a forgotten value of a subject in play: the user,
  or a person the sentence names (:func:`repository.value_fingerprint_with`; written since
  Phase 10A — values forgotten before have no such mark).

Words the user's own message brings up are not held against a sentence: "Kervan'dan
ayrıldım" may be answered with "Kervan'dan ayrıldığınızı söylediniz".

The reply guard (:mod:`lazis.conversation.people`) and what LAZIS brings up on its own
(:mod:`lazis.memory.proactive`) use it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from itertools import combinations
from typing import Literal

from lazis.memory import graphstore as gs
from lazis.memory import relations, text
from lazis.memory import repository as repo
from lazis.memory.models import USER_ID
from lazis.storage.driver import Connection

Kind = Literal["relationship", "value"]
MIN_VALUE = 3  # shorter spans ("ev", "iş") are never a forgotten value on their own
# Words that speak of a relationship without naming its type.
_GENERIC = frozenset({"iliski", "iliskisi", "iliskiniz", "iliskileri", "akraba", "akrabasi",
                      "akrabalik", "yakinlik", "baglanti", "bag"})  # fmt: skip


@dataclass(frozen=True)
class Index:
    key: bytes = b""
    fps: frozenset[str] = frozenset()
    names: Mapping[str, tuple[str, ...]] = field(default_factory=dict[str, tuple[str, ...]])
    allowed: frozenset[str] = frozenset()  # folded words of the user's message
    in_message: tuple[str, ...] = ()  # stored people the user's message names

    @property
    def empty(self) -> bool:
        return not self.fps

    def named(self, words: Sequence[str]) -> list[str]:
        """Stored people the words name (suffix-tolerant), in no particular order."""
        out: list[str] = []
        for k in text.candidate_keys(list(words)):
            if k in self.names and text.mentions_name(list(words), k):
                out += [i for i in self.names[k] if i not in out]
        return out

    def speaks_of(self, sentence: str) -> Kind | None:
        if self.empty:
            return None
        words = text.words(sentence)
        if not words:
            return None
        named = self.named(words)
        if self._relationship(words, named):
            return "relationship"
        if self._value(words, [None, *named]):
            return "value"
        return None

    def _relationship(self, words: list[str], named: list[str]) -> bool:
        found = relations.types_in(words)
        # The user's own relation ("kuzeniniz", "arkadaşım") is about the user and a person;
        # "kuzeni", "kardeşiydi" (or "ilişki") about two people.
        own = {t for t, e in found if relations.first_person(e) or relations.second_person(e)}
        third = {t for t, _ in found if t not in own}
        # "… arasında kayıtlı bir ilişki bulunmuyor" says nothing of the forgotten one; a named
        # type ("kuzeniydi") always does.
        generic = bool(_GENERIC.intersection(words)) and not _negated(words)
        # Two names in the sentence: the pair is theirs. One: the other end may be in the
        # user's message ("Mehmet bu kişilerden hangisinin kuzeniydi?" after "Mehmet, Ahmet'in
        # neyi oluyor?").
        names = {self._key_of(i) for i in named}
        others = named if len(names) > 1 else [*named, *self.in_message]
        pairs = [(a, b, third) for a, b in combinations(dict.fromkeys(others), 2)
                 if (a in named or b in named) and (third or generic)]  # fmt: skip
        pairs += [(USER_ID, e, own) for e in named if own]
        for a, b, types in pairs:
            if gs.pair_fingerprint_with(self.key, a, b) in self.fps:
                return True
            for t in types:
                if (
                    gs.rel_fingerprint_with(self.key, a, t, b) in self.fps
                    or gs.rel_fingerprint_with(self.key, b, t, a) in self.fps
                ):
                    return True
        return False

    def _key_of(self, entity_id: str) -> str:
        return next((k for k, ids in self.names.items() if entity_id in ids), entity_id)

    def _value(self, words: list[str], subjects: Sequence[str | None]) -> bool:
        for span in text.candidate_keys(words):
            parts = span.split()
            if len(span) < MIN_VALUE or all(p in text.STOP_WORDS for p in parts):
                continue
            if _brought_up(parts, self.allowed):
                continue
            for s in subjects:
                if repo.value_fingerprint_with(self.key, s, span) in self.fps:
                    return True
        return False


def _negated(words: Sequence[str]) -> bool:
    return any(
        w in ("yok", "degil", "degildir", "bilmiyorum")
        or w.endswith(("miyor", "muyor", "miyorum", "muyorum", "mez", "maz"))
        for w in words
    )


def _brought_up(parts: list[str], allowed: frozenset[str]) -> bool:
    """The span's words are the user's own in this message (suffixes aside)."""
    return bool(allowed) and all(
        any(a.startswith(text.stem_prefix(p)) or p.startswith(text.stem_prefix(a))
            for a in allowed)
        for p in parts if p not in text.STOP_WORDS
    )  # fmt: skip


def has_any(conn: Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM memory_suppressions WHERE reason = 'forgotten' LIMIT 1"
        ).fetchone()
        is not None
    )


def load(conn: Connection, *, message: str = "") -> Index:
    """Everything forgotten (fingerprints only) and the names of stored people. Empty — and
    no further reads — when nothing was ever forgotten."""
    fps = repo.forgotten_fingerprints(conn)
    if not fps:
        return Index()
    names: dict[str, list[str]] = {}
    for key, eid in repo.alias_index(conn):
        ids = names.setdefault(key, [])
        if eid not in ids:
            ids.append(eid)
    allowed = frozenset(w for w in text.words(message) if w not in text.STOP_WORDS)
    index = Index(repo.fingerprint_key(conn), fps, {k: tuple(v) for k, v in names.items()}, allowed)
    return replace(index, in_message=tuple(index.named(text.words(message))))
