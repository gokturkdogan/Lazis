"""People the user's message does not settle, as a check on text (Phase 10A, ADR-0021).

Recall already holds back what is stored about namesakes the message does not tell apart (or
a name with an open "which one?" question) and tells the model to ask
(:func:`lazis.memory.retrieval._unsettled`). The model still answers about one of them, from
the chat history or by guessing:

* "Ahmet'in kardeşi Mehmet'tir. Ancak … hangi Ahmet?" (Phase 7 sessions, 3.ask) — a stored
  fact of one of them, said as *the* answer;
* "Komşunuz olan Ahmet Bey'in emekli olduğunu anladım." (Phase 9.1 namesakes, a2 in chat) —
  what the user just said, attached to one of them.

A sentence is **certain about an unsettled person** when it names the person, is not a
question or a condition ("… kastediyorsanız"), and either

* **fact** — states a stored value of one candidate, or one of their relationships (the other
  person and the relation word), without the label that says which candidate ("Komşunuz
  Ahmet mimar" says which; "Ahmet mimar" does not); or
* **label** — gives the label of some candidates, not all (or of the stored one while another
  of that name may exist), together with what the user's message says or with "kastettiğiniz
  / bahsettiğiniz": it decides which one was meant.

Words the user's message itself says are the user's, not a guess. Listing every candidate with
its label ("Komşunuz Ahmet de iş arkadaşınız Ahmet de kayıtlı") is not certainty.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from lazis.memory import graphstore as gs
from lazis.memory import relations, text
from lazis.memory import repository as repo
from lazis.memory.models import CURRENT, USER_ID
from lazis.storage.driver import Connection

Kind = Literal["fact", "label"]
_MIN_WORD = 3
# "kastediyorsanız", "isterseniz", "eğer", "ise", "olduysa": a condition, not a claim.
_CONDITION = re.compile(r"(?:saniz|seniz|sam|sem|sak|sek|ysa|yse|yorsa|dise|disa|mise|misa)$")
# "kastettiğiniz", "bahsettiğiniz", "söz ettiğiniz", "kastediyorsunuz": which one was meant.
_MEANT = re.compile(r"^(?:kastet|kasted|bahset|bahsed|soz)")


@dataclass(frozen=True)
class Candidate:
    entity_id: str
    label_types: frozenset[str]  # relation types to the user ("komşu" → neighbor)
    values: tuple[tuple[str, ...], ...]  # folded significant words of each stored value
    links: tuple[tuple[str, str], ...]  # (the other person's name key, relation type)


@dataclass(frozen=True)
class Unsettled:
    name: str  # as stored ("Ahmet")
    key: str  # name key ("ahmet")
    candidates: tuple[Candidate, ...]
    others_unknown: bool  # one stored, and another of that name may exist (open question)


def load(conn: Connection, entity_ids: Sequence[str]) -> tuple[Unsettled, ...]:
    """The unsettled people, grouped by name, from recall's unsettled entity ids."""
    groups: dict[str, list[Candidate]] = {}
    names: dict[str, str] = {}
    for eid in dict.fromkeys(entity_ids):
        e = repo.get_entity(conn, eid)
        if e is None or e.is_user:
            continue
        names.setdefault(e.name_key, e.name)
        groups.setdefault(e.name_key, []).append(_candidate(conn, eid, e.relation))
    out: list[Unsettled] = []
    for key, cands in groups.items():
        stored = repo.find_entities(conn, key)
        if any(e.id not in entity_ids for e in stored):
            continue  # the message picked one of them ("komşum Ahmet"): settled
        out.append(Unsettled(names[key], key, tuple(cands), others_unknown=len(stored) < 2))
    return tuple(out)


def _candidate(conn: Connection, eid: str, relation: str | None) -> Candidate:
    labels: set[str] = set()
    if relation and (t := relations.lexicon(relation)) is not None:
        labels.add(t)
    links: list[tuple[str, str]] = []
    for r in gs.relationships_of(conn, eid, statuses=CURRENT):
        other = r.target_id if r.source_id == eid else r.source_id
        if other == USER_ID:
            labels.add(r.type)
            continue
        o = repo.get_entity(conn, other)
        if o is not None:
            links.append((o.name_key, r.type))
    values = tuple(
        ws
        for m in repo.memories_for_subject(conn, eid)
        if m.status == "active" and (ws := _significant(text.words(m.value)))
    )
    return Candidate(eid, frozenset(labels), values, tuple(links))


def _significant(words: Sequence[str]) -> tuple[str, ...]:
    return tuple(w for w in words if len(w) >= _MIN_WORD and w not in text.STOP_WORDS)


def _has(words: Sequence[str], want: str) -> bool:
    """A sentence word is ``want`` with Turkish suffixes ("mimar" in "mimarsınız")."""
    stem = text.stem_prefix(want)
    return any(w == want or (w.startswith(stem) and len(w) - len(want) <= 6) for w in words)


def question(sentence: str) -> bool:
    return sentence.rstrip(" \t\"'»”)").endswith("?")


def conditional(words: Sequence[str]) -> bool:
    return any(w in ("eger", "ise", "sayet") or _CONDITION.search(w) for w in words)


def certain(sentence: str, u: Unsettled, message: str) -> Kind | None:
    words = text.words(sentence)
    if not text.mentions_name(words, u.key) or question(sentence) or conditional(words):
        return None
    said = _significant(text.words(message))
    types = {t for t, _ in relations.types_in(words)}
    labeled = [c for c in u.candidates if c.label_types & types]
    for c in u.candidates:
        if c in labeled:
            continue
        for value in c.values:
            if all(_has(words, w) for w in value) and not all(_has(said, w) for w in value):
                return "fact"
        for other, t in c.links:
            named = text.mentions_name(words, other)
            if named and t in types and not text.mentions_name(list(said), other):
                return "fact"
    if labeled and (len(labeled) < len(u.candidates) or u.others_unknown):
        content = [
            w for w in said
            if len(w) >= 4 and not text.mentions_name([w], u.key) and not _relation_word(w)
        ]  # fmt: skip
        if any(_has(words, w) for w in content) or any(_MEANT.match(w) for w in words):
            return "label"
    return None


def _relation_word(w: str) -> bool:
    return relations.match_at([w], 0) is not None
