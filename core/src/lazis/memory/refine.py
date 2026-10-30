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

from lazis.memory import extraction, registry, temporal, text
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
# Values a "not" right after them denies today ("Kervan'da çalışmıyorum", "öğretmen değilim").
_DENIABLE = frozenset({"employer", "location", "occupation"})
_STILL = frozenset({"artik", "hala", "halen", "simdi"})
# "…, ayrıca eğitmenlik yapıyorum", "eğitmenlik de yapıyorum": one more job, next to today's.
_ALSO = ("ayrica", "ayni zamanda", "yani sira", "bir de", "ek olarak", "hem de")
_ALSO_PREDICATES = frozenset({"occupation", "employer"})
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
        if tense == "current" and temporal.left(clause, c.value):
            tense = "past"  # "Kervan'dan ayrıldım": Kervan is history
        if c.predicate in _DENIABLE and temporal.is_leaving(c.value):
            # "Ahmet doktorluğu bıraktı" proposed as Ahmet's job "doktorluğu bıraktı" (Phase 9.1
            # runs 2 and 3, t15): a leaving is no job, no workplace, no home — never today's
            # value. It ends the stored one it names, if any (`service._apply_past`).
            count("leaving_as_value")
            out_f.append(
                replace(e, candidate=replace(c, tense="past", change=False, replaces=None))
            )
            continue
        if c.change and not temporal.change_marked(msg):
            c = replace(c, change=False)
            count("change_not_said")
        if c.predicate in _DENIABLE and (
            said_with_not(clause, c.value)
            or (c.predicate == "occupation" and denied_as_verb(clause, c.value))
        ):
            # "Artık Kervan Lojistik'te çalışmıyorum" given as employer Kervan (seen with Gemma):
            # history when it ended, nothing when it was only denied — never today's value.
            count("said_with_not")
            if not _PRESENT.search(" ".join(text.words(clause))):
                continue
            c = replace(c, tense="past", change=False, replaces=None)
        if (
            c.predicate in _ALSO_PREDICATES
            and not c.change
            and tense == "current"
            and said_as_also(msg, c.value)
        ):
            c = replace(c, also=True)
            count("also_current")
        if c.predicate in _PASSING_PREDICATES and _passing(clause, c.quote):
            count("ephemeral")  # a passing state: not kept
            continue
        if c.event_time is None and (when := temporal.time_phrase(clause)):
            c = replace(c, event_time=when)
        if c.predicate == "goal" and tense == "future" and c.event_time:
            # "Seneye emekli olacağım": a dated intention is a plan, with the user's own time.
            plan = (c.quote or c.value).strip()[:120]
            c = replace(c, predicate="plan", value=plan, change=False, replaces=None)
            count("future_as_plan")
        elif c.predicate not in _TIMELESS:
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
        if tense == "current" and temporal.left(clause, rc.target.name):
            tense = "past"
        if (
            not rc.negated
            and rc.status == "active"
            and not _between_people(rc.type)
            and said_with_not(clause, rc.target.name)
        ):
            # The same, as a workplace or a place (also what an employer fact becomes): ended
            # with "artık", denied without it — as if the model had said "not" itself.
            ended = bool(_PRESENT.search(" ".join(text.words(clause))))
            rc = replace(rc, negated=True, status="ended" if ended else rc.status, change=ended)
            count("said_with_not")
        if not rc.negated:
            if tense == "past" and rc.status == "active" and not relationship_over(clause, rc.type):
                # "Kız kardeşim Elif eskiden İzmir'de yaşıyordu": the past is about where
                # Elif lived, not about being a sister (seen with Gemma).
                count("past_about_the_person")
            elif tense == "past" and rc.status == "active":
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
    # A workplace or city that became history leaves room for the current one the same message
    # said as a relationship ("Kervan'dan ayrıldım, artık Atlas'tayım").
    current = [f for f in out_f if f.candidate.tense != "past"]
    out_f += extraction.facts_from_relations(current, out_r)
    return out_f, out_r


# A first-person past verb ("arkadaştık", "birlikte çalışıyorduk", "evliydik"): the user's
# side of it is what was.
_WE_WERE = re.compile(r"(?:d|t)[iu][mk]$")
_ROLE_WAS = re.compile(r"(?:y?d|t)[iu](?:m|k|n|niz|nuz)?$")


def relationship_over(clause: str, key: str) -> bool:
    """Whether a past clause says the relationship itself is over. Between people the
    relation word is often only who someone is ("Kardeşim Elif eskiden öğretmendi"): it is
    over when the relation word is in the past ("Ahmet eskiden komşumdu", "eski komşum") or
    the user says what they were together ("Eskiden Burak'la arkadaştık"). A workplace, a
    place or a project is the verb itself ("Kervan'da çalışıyordum")."""
    t = relations_vocab.TYPES.get(key)
    if t is None or not _between_people(key):
        return True
    words = text.words(clause)
    stems = [w.split()[-1] for w in t.words] or [text.words(t.label)[-1][:4]]
    for i, w in enumerate(words):
        role = next((st for st in stems if w.startswith(st)), None)
        if role is not None and (
            _ROLE_WAS.search(w[len(role) :]) or (i and words[i - 1] == "eski")
        ):
            return True
    return any(_WE_WERE.search(w) for w in words)


def _between_people(key: str) -> bool:
    t = relations_vocab.TYPES.get(key)
    people = relations_vocab.PEOPLE
    return t is not None and t.source_kinds == people and t.target_kinds == people


def said_with_not(clause: str, value: str) -> bool:
    """The first word after ``value`` denies it: "Artık Kervan Lojistik'te çalışmıyorum",
    "İstanbul'da artık yaşamıyorum", "öğretmen değilim". Not "Kervan'da değil, Atlas'ta
    çalışıyorum" for Atlas, nor "Kervan'da çalışıyorum ama mutlu değilim"."""
    words, key = text.words(clause), " ".join(text.words(value))
    n = len(key.split())
    for i in range(len(words) - n + 1):
        if n and text.mentions_name(words[i : i + n], key):
            # A suffix after an apostrophe ("te", "da") is a word of its own here.
            after = [w for w in words[i + n :] if len(w) > 3 and w not in _STILL]
            return bool(after) and bool(_NEGATED.search(after[0]))
    return False


_MIN_STEM = 5


def said_as_also(message: str, value: str) -> bool:
    """ "Yazılım geliştiricisiyim, ayrıca eğitmenlik yapıyorum" for "eğitmen" (the cue comes
    before it), "Eğitmenlik de yapıyorum" (right after it) — not for the first job."""
    # A name keeps its case ending: "Kervan'da çalışıyorum" is not "Kervan da" (Phase 9.1,
    # Phase 9 learning regression t08 / c07).
    words = text.words(re.sub(r"['’`´]", "", message))
    vw = text.words(value)
    if not vw:
        return False
    stem = temporal.occupation_stem(vw[0])[:_MIN_STEM] or vw[0]
    joined = " ".join(words)
    for i, w in enumerate(words):
        if not w.startswith(stem):
            continue
        after = words[i + len(vw) : i + len(vw) + 2]
        if after and len(after[0]) <= 3 and after[0] not in ("de", "da"):
            after = after[1:]  # the case ending of a name ("Atlas'ta da")
        before = " ".join(words[:i])
        if after[:1] in (["de"], ["da"]) or any(f" {cue} " in f" {before} " for cue in _ALSO):
            return True
    return any(f" {cue} " in f" {joined} " for cue in ("hem",)) and words.count("hem") >= 2


def denied_as_verb(clause: str, value: str) -> bool:
    """A negated word of the clause is the occupation's own verb ("Ahmet artık yazılım
    geliştirmiyor" for "yazılım geliştiricisi"). The other words of the value must be there
    too, so that "kod geliştirmiyor" does not end "oyun geliştiricisi"."""
    vw = text.words(value)
    if not vw:
        return False
    # Phase 9.1: the model gave only the old value, and it stayed current (Phase 6 sessions
    # 3.memory, "Ahmet artık yazılım geliştirmiyor, kendi restoranını açtı").
    stem = temporal.occupation_stem(vw[-1])
    if len(stem) < _MIN_STEM:
        return False
    words = text.words(clause)
    rest = vw[:-1]
    for i, w in enumerate(words):
        if w.startswith(stem) and w != vw[-1] and _NEGATED.search(w[len(stem) :]):
            before = words[max(0, i - len(rest)) : i]
            return all(any(b.startswith(r[:_MIN_STEM]) for b in before) for r in rest)
    return False


def _passing(clause: str, quote: str | None) -> bool:
    """ "Bugün çok yorgunum": "bugün" is about what was quoted. In "Ahmet bugün aradı, satranç
    kulübüne yazılmış" it is about the call — the quoted fact lasts."""
    words = " ".join(text.words(clause))
    if not _NOW.search(words) or _LASTING.search(words):
        return False
    q = text.words(quote or "")
    if not q or _NOW.search(" ".join(q)):
        return True
    rest = [w for w in text.words(_NOW.sub(" ", words)) if w not in set(q)]
    return len(rest) <= 1  # the quote is the whole clause but the time word


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
