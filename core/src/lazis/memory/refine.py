"""Checks between the model's validated answer and the memory (Phase 9; learning and explicit
requests alike). Each rule is read from the user's own words; nothing here adds a fact or a
relationship the model did not propose — it only corrects *when* or *whose* it is, or holds
it back:

* **time** (:mod:`temporal`): a past value becomes history (it never replaces today's), a
  future one becomes a plan, a past relationship is ended, a future one planned;
* **change**: the model's "it changed" counts only when the words say so ("artık",
  "taşındı", "… beri"); otherwise a different value is a conflict to ask about;
* **time named**: the user's time phrase ("2024'te", "geçen ay") is kept, never a date;
* **someone else's relatives**: "Annemin üç kardeşi var: Ayşe, Fatma ve Zeynep" are not the
  user's siblings (they are the user's aunts or uncles: ``parent_sibling``); "Arkadaşımın
  kardeşi Can" is not the user's sibling at all.

Every change is counted (diagnostics: counts only, never content).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import replace

from lazis.memory import registry, temporal, text
from lazis.memory import relations as relations_vocab
from lazis.memory.extraction import Extracted, ExtractedRel

# Predicates that are about time already (an event in the past is still an event).
_TIMELESS = frozenset({"event", "plan", "goal", "decision", "note", "project_milestone"})
# "Ahmet'te çalışmıyorum", "artık sigara içmiyorum", "değil", "yok": a negated present.
_NEGATED = re.compile(r"(?:m[iu]yor\w*|maz\w*|mez\w*|m[ae]d[iu]\w*|degil\w*)$|^yok$")
_PRESENT = re.compile(r"\b(artik|simdi|su an|su sira|halen|hala)\b")
# "annemin", "babamın", "eşimin", "arkadaşımın": a relative of the user, unnamed, as possessor.
_MY_RELATIVES = re.compile(r"^\w+(?:im|um|m)(?:in|un|nin|nun)$")
_PARENT = frozenset({"annemin", "babamin", "anneannemin", "babaannemin"})
# A passing state ("Bugün çok yorgunum", "Şu an canım pizza istiyor"): not a lasting fact
# unless the words say it lasts ("hiç", "her zaman", "genelde").
_NOW = re.compile(r"\b(bugun|su an|su anda|bu aksam|bu sabah|bu gece|az once|biraz once|"
                  r"bu ara|bugunlerde)\b")  # fmt: skip
_LASTING = re.compile(
    r"\b(hic|her zaman|genelde|genellikle|hep|her gun|her sabah|her aksam|asla|eskiden beri|"
    r"yillardir|cok severim|bayilirim|nefret ederim)\b"
)
_PASSING_PREDICATES = frozenset({"note", "likes", "dislikes", "interest", "habit"})
_COUNTS = frozenset({"iki", "uc", "dort", "bes", "alti", "yedi", "bir", "cok", "birkac", "kac"})


def _negated(clause: str) -> bool:
    return any(_NEGATED.search(w) for w in text.words(clause))


def refine(
    facts: Sequence[Extracted],
    relations: Sequence[ExtractedRel],
    messages: Mapping[str, str],
    counts: dict[str, int],
) -> tuple[list[Extracted], list[ExtractedRel]]:
    """``messages``: message id → the user's text. ``counts`` is added to (reason → n)."""

    def count(reason: str) -> None:
        counts[reason] = counts.get(reason, 0) + 1

    out_f: list[Extracted] = []
    for e in facts:
        c = e.candidate
        msg = messages.get(e.message_id, "")
        clause = temporal.clause_of(msg, c.quote, c.value)
        tense = temporal.tense(clause)
        if c.change and not temporal.change_marked(msg):
            c = replace(c, change=False)
            count("change_not_said")
        words = " ".join(text.words(clause))
        if c.predicate in _PASSING_PREDICATES and _NOW.search(words) and not _LASTING.search(words):
            count("ephemeral")  # a passing state: not kept
            continue
        if c.event_time is None and (when := temporal.time_phrase(clause)):
            c = replace(c, event_time=when)
        if c.predicate not in _TIMELESS:
            if tense == "future":
                plan = (c.quote or c.value).strip()[:120]
                c = replace(c, predicate="plan", value=plan, change=False, replaces=None)
                count("future_as_plan")
            elif tense == "past" and not _negated_current(clause):
                c = replace(c, tense="past", change=False)
                count("past_as_history")
        out_f.append(replace(e, candidate=c))

    out_r: list[ExtractedRel] = []
    for r in relations:
        rc = r.candidate
        msg = messages.get(r.message_id, "")
        clause = temporal.clause_of(msg, rc.quote, rc.target.name)
        if (rc.change or rc.correction) and not temporal.change_marked(msg):
            rc = replace(rc, change=False, correction=False)
            count("change_not_said")
        if rc.time_text is None and (when := temporal.time_phrase(clause)):
            rc = replace(rc, time_text=when)
        tense = temporal.tense(clause)
        if not rc.negated:
            if tense == "past" and rc.status == "active":
                rc = replace(rc, status="ended")
                count("past_relation_ended")
            elif tense == "future" and rc.status == "active":
                rc = replace(rc, status="planned")
                count("future_relation_planned")
            elif (
                tense == "current"
                and rc.status == "ended"
                and _PRESENT.search(" ".join(text.words(clause)))
                and not _negated(clause)
            ):
                rc = replace(rc, status="active")  # "artık Pusula'dayım": true now
                count("current_relation_active")
        if rc.source is None:
            kind = _someone_elses_relative(clause, rc.type)
            if kind == "drop":
                count("relative_of_a_relative")
                continue
            if kind is not None:
                rc = replace(rc, type=kind)
                count("parent_sibling")
        out_r.append(replace(r, candidate=rc))
    return out_f, out_r


def _negated_current(clause: str) -> bool:
    """ "Artık sigara içmiyorum" is a present statement (a change), not a past one."""
    return bool(_PRESENT.search(" ".join(text.words(clause)))) and _negated(clause)


def _someone_elses_relative(clause: str, type_key: str) -> str | None:
    """None: the relationship is the user's own. "drop": it belongs to someone the user only
    refers to ("arkadaşımın kardeşi"). Otherwise the type it really is for the user."""
    words = text.words(clause)
    nouns = relations_vocab.TYPES.get(type_key)
    if nouns is None:
        return None
    for i in range(len(words)):
        m = relations_vocab.match_at(words, i)
        if m is None or m[0] != type_key:
            continue
        before = [x for x in words[max(0, i - 3) : i] if not x.isdigit() and x not in _COUNTS]
        owner = before[-1] if before else ""
        if owner and _MY_RELATIVES.match(owner) and owner not in ("benim", "bizim"):
            if owner in _PARENT and type_key == "sibling":
                return "parent_sibling"
            return "drop"
    return None


def single_valued(predicate: str) -> bool:
    p = registry.get(predicate)
    return p is not None and p.cardinality == "single"
