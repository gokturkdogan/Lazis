"""Namesakes stated in one message (Phase 7.2, ADR-0018).

"İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım." names two different people. Resolving
each extracted candidate on its own against the store cannot see that: the second Ahmet met
the first one, created a moment earlier from the same message, and became a "which Ahmet?"
question — or was attached to him (measured with Gemma in Phase 7.1: five of five times only
one Ahmet was stored, and a later "Ahmet'in doğum günü" went to him without asking). The
user's own words decide it here, before anything is written:

* :func:`stated` finds counted names ("iki Ahmet", "Ahmet adında iki arkadaşım", "üç Ayşe")
  with their slots ("biri …, diğeri …", "kuzenim, komşum ve iş arkadaşım"), and names said to
  be one person with several roles ("Ahmet hem komşum hem iş arkadaşım");
* :func:`plan` gives every candidate about such a name the entity of its slot — the stored
  namesake the slot's words identify uniquely, or a new one — and marks the slot entities as
  different people. A slot the model left out is still created from the user's words, so the
  store never holds fewer of them than the user said (a bare "Ahmet" then asks instead of
  picking the only one stored). A candidate that fits no slot is left to the resolver, which
  sees the namesakes and asks.

Deterministic, no model call. A message without a counted or "hem … hem" name costs one pass
over its words.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace

from lazis.ids import utc_now_iso
from lazis.memory import graphstore as gs
from lazis.memory import relations, resolver, text
from lazis.memory import repository as repo
from lazis.memory.extraction import Extracted, ExtractedRel
from lazis.memory.models import USER_ID, EntityRef
from lazis.storage.driver import Connection
from lazis.storage.unit_of_work import Actor, UnitOfWork

COUNTS = {"iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6, "2": 2, "3": 3, "4": 4, "5": 5}
_BETWEEN = frozenset({"farkli", "ayri", "tane", "adet", "ayri ayri"})
_NAMED = frozenset({"adinda", "adli", "isminde", "isimli"})
# Words that start a sentence or a slot but are not names.
_NOT_NAMES = frozenset(
    {"hem", "bir", "biri", "birisi", "digeri", "oburu", "ben", "biz", "o", "bu", "su", "benim",
     "bizim", "onun", "lazis", "ve", "ama", "fakat", "ayrica", "bugun", "dun", "yarin",
     *COUNTS}
)  # fmt: skip
_SLOT_WORDS = r"(?:biri|birisi|digeri|oburu|ilki|birincisi|ikincisi|ucuncusu|dorduncusu|sonuncusu)"
_MARKERS = re.compile(rf"\b{_SLOT_WORDS}\b")
_SPLIT = re.compile(rf"\b{_SLOT_WORDS}\b|[,;]|\bve\b|\bile\b")
# Slot words that carry nothing ("tanıyorum", "var", "hayatımda").
_EMPTY = frozenset(
    {"tanirim", "taniyorum", "var", "vardir", "hayatimda", "cevremde", "benim", "de", "da",
     "ise", "olan", "kisi", "kisiler", "insan", "arkadas"}
)  # fmt: skip
_MODIFIERS = frozenset(
    {"eski", "yeni", "sevgili", "en", "yakin", "iyi", "universiteden", "okuldan", "isten",
     "lise", "liseden", "askerden", "mahalleden"}
)  # fmt: skip
_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")


@dataclass(frozen=True)
class Slot:
    words: str  # folded slot text ("is arkadasim")
    surface: str  # as written ("iş arkadaşım")
    type: str | None  # a relationship to the user the words name ("colleague"), if any
    label: str | None  # the entity's relation label ("iş arkadaşı", "eski patronu")
    extra: tuple[str, ...] = ()  # folded words said of it after the slot ("biri komşum, mimar")


@dataclass(frozen=True)
class Group:
    key: str  # name key
    name: str  # as written
    count: int
    slots: tuple[Slot, ...] = ()  # empty: the slots could not be read


@dataclass(frozen=True)
class Stated:
    groups: tuple[Group, ...] = ()
    same: frozenset[str] = frozenset()  # name keys said to be one person ("hem … hem")

    def __bool__(self) -> bool:
        return bool(self.groups or self.same)


def _base(token: str) -> str:
    return re.split(r"['’]", token, maxsplit=1)[0]


def _is_name(token: str) -> bool:
    b = _base(token)
    return len(b) >= 2 and b[0].isupper() and text.fold(b) not in _NOT_NAMES


def _first_person(word: str) -> bool:
    return word.endswith("m") or word.endswith("miz")


def slot_of(surface: str, name_key: str) -> Slot | None:
    folded = [w for w in text.words(surface) if w not in _EMPTY and text.name_key(w) != name_key]
    if not folded:
        return None
    surface_of = {text.fold(_base(t)): _base(t) for t in _WORD.findall(surface)}
    mods = [surface_of.get(w, w) for w in folded if w in _MODIFIERS]
    core = [w for w in folded if w not in _MODIFIERS]
    if not core:
        return None
    phrase = " ".join(core)
    key = relations.lexicon(phrase) if _first_person(core[-1]) else None
    label: str | None = None
    if key is not None:
        label = " ".join([*mods, relations.TYPES[key].label])
    elif _first_person(core[-1]) and len(core[-1]) > 3:
        # Not in the vocabulary ("eski patronum"): the user's words in the third person.
        words = [surface_of.get(w, w) for w in core]
        label = " ".join([*mods, *words[:-1], words[-1][:-1]])
    words = " ".join(folded)
    return Slot(words=words, surface=surface.strip(" .:;,"), type=key, label=label)


def _slots(region: str, name_key: str, count: int) -> tuple[Slot, ...]:
    """The slots after a counted name: "biri komşum, diğeri iş arkadaşım" / "kuzenim, komşum
    ve iş arkadaşım". Only when there are exactly as many as the user counted."""
    cut = re.split(r"[:;]", region, maxsplit=1)
    body = cut[1] if len(cut) == 2 else region
    folded = text.fold(body)
    m = _MARKERS.search(folded)
    if len(cut) != 2 and m is None:
        return ()
    if m is not None and len(cut) != 2:
        body = body[m.start() :]
    # Split on the folded text (same length as the original: offsets map back).
    pieces: list[str] = []
    last = 0
    folded = text.fold(body)
    for sep in _SPLIT.finditer(folded):
        pieces.append(body[last : sep.start()])
        last = sep.end()
    pieces.append(body[last:])
    marks = list(_MARKERS.finditer(folded))
    if marks:
        # One slot per slot word, whatever follows it in its piece: "biri komşum, mimar.
        # Diğeri iş arkadaşım, muhasebeci." is two people, not "komşum" and "mimar" (Phase 9.1:
        # Phase 8 bootstrap n02 put both jobs on one Ahmet).
        ends = [m.start() for m in marks[1:]] + [len(body)]
        pieces = [body[m.end() : e] for m, e in zip(marks, ends, strict=True)]
        slots = [s for s in (_marked(p, name_key) for p in pieces) if s is not None]
        return tuple(slots) if len(slots) == count else ()
    slots = [s for s in (slot_of(p, name_key) for p in pieces) if s is not None]
    return tuple(slots) if len(slots) == count else ()


def _marked(piece: str, name_key: str) -> Slot | None:
    """The slot after one slot word: its first part names it ("komşum"), the rest is said of
    it ("mimar")."""
    parts = [x for x in re.split(r"[,;.!?]|\bve\b|\bile\b", piece) if x.strip()]
    for i, part in enumerate(parts):
        slot = slot_of(part, name_key)
        if slot is None:
            continue
        extra = tuple(
            w for x in parts[i + 1 :] for w in text.words(x)
            if w not in _EMPTY and text.name_key(w) != name_key
        )  # fmt: skip
        return replace(slot, extra=extra)
    return None


def _region(sentences: Sequence[str], i: int, end: int) -> str:
    """The text after a counted name: the rest of its sentence, and the next sentence when it
    goes on with the slots ("İki Ahmet tanıyorum. Biri komşum, diğeri iş arkadaşım.")."""
    region = sentences[i][end:]
    following: list[str] = []
    for nxt in sentences[i + 1 :]:  # "Biri komşum, mimar. Diğeri iş arkadaşım, muhasebeci."
        if not _MARKERS.match(text.fold(nxt.lstrip())):
            break
        following.append(nxt)
    if following:
        region = f"{region.rstrip(' .!?')}: {' '.join(following)}"
    return region


def stated(message: str) -> Stated:
    groups: list[Group] = []
    same: set[str] = set()
    sentences = re.split(r"(?<=[.!?])\s+", message)
    for si, sentence in enumerate(sentences):
        toks = list(_WORD.finditer(sentence))
        for i, t in enumerate(toks):
            f = text.fold(t.group(0))
            name, count, end = "", 0, 0
            if f in COUNTS:
                j = i + 1
                while j < len(toks) and text.fold(toks[j].group(0)) in _BETWEEN:
                    j += 1
                if j < len(toks) and _is_name(toks[j].group(0)):
                    # "İki Ahmet Yılmaz": a surname belongs to the name (until a suffix).
                    k = j + 1
                    while (k < len(toks) and k <= j + 2 and _is_name(toks[k].group(0))
                           and not re.search(r"['’]", toks[k - 1].group(0))):  # fmt: skip
                        k += 1
                    name = " ".join(_base(x.group(0)) for x in toks[j:k])
                    count, end = COUNTS[f], toks[k - 1].end()
            elif _is_name(t.group(0)) and i + 2 < len(toks):
                # "Ahmet adında iki arkadaşım var"
                if text.fold(toks[i + 1].group(0)) in _NAMED:
                    for k in (i + 2, i + 3):
                        if k < len(toks) and text.fold(toks[k].group(0)) in COUNTS:
                            name, count = _base(t.group(0)), COUNTS[text.fold(toks[k].group(0))]
                            end = toks[k + 1].end() if k + 1 < len(toks) else toks[k].end()
                            break
            if not name or count < 2:
                continue
            key = text.name_key(name)
            if any(g.key == key for g in groups):
                continue
            groups.append(Group(key, name, count, _slots(_region(sentences, si, end), key, count)))
        # "Ahmet hem komşum hem iş arkadaşım": one person, several roles.
        folded = [text.fold(t.group(0)) for t in toks]
        hems = [i for i, w in enumerate(folded) if w == "hem"]
        if len(hems) >= 2:
            before = [t for t in toks[: hems[0]] if _is_name(t.group(0))]
            after_names = [t for t in toks[hems[0] :] if _is_name(t.group(0))]
            if len(before) == 1 and not after_names:
                same.add(text.name_key(_base(before[0].group(0))))
        if "ayni zamanda" in " ".join(folded):
            names = [t for t in toks if _is_name(t.group(0))]
            if len({text.name_key(_base(t.group(0))) for t in names}) == 1:
                same.add(text.name_key(_base(names[0].group(0))))
    counted = {g.key for g in groups}
    return Stated(tuple(groups), frozenset(same - counted))


# ----- planning -------------------------------------------------------------------------
@dataclass
class PlanReport:
    """What a plan did (ids and counts; no content)."""

    entities_created: list[str] = field(default_factory=list[str])
    assigned: int = 0
    unassigned: int = 0
    distinctions: int = 0
    groups: int = 0


def _refs(fact: Extracted | None, rel: ExtractedRel | None) -> list[tuple[str, EntityRef]]:
    if fact is not None:
        e = fact.candidate.entity
        return [("entity", e)] if e is not None else []
    assert rel is not None
    out: list[tuple[str, EntityRef]] = []
    if rel.candidate.source is not None:
        out.append(("source", rel.candidate.source))
    out.append(("target", rel.candidate.target))
    return out


def _with_user(rel: ExtractedRel, end: str) -> bool:
    other = rel.candidate.target if end == "source" else rel.candidate.source
    return other is None or text.name_key(other.name) in {"kullanici", "ben", "user", ""}


def _existing_for(conn: Connection, key: str, slot: Slot) -> list[str]:
    """Stored namesakes the slot's words identify: the relationship to the user, the label, or
    a stored value ("öğretmen")."""
    out: list[str] = []
    for e in repo.find_entities(conn, key):
        if e.status != "active" or e.kind != "person":
            continue
        if slot.type is not None:
            mine = gs.relationships_between(conn, USER_ID, e.id)
            if any(r.type == slot.type and r.status in ("active", "planned") for r in mine):
                out.append(e.id)
                continue
        if slot.label and e.relation and text.fold(e.relation) == text.fold(slot.label):
            out.append(e.id)
            continue
        if slot.type is None and slot.label is None:
            values = {text.fold(m.value) for m in repo.memories_for_subject(conn, e.id)}
            if slot.words in values or (e.description and text.fold(e.description) == slot.words):
                out.append(e.id)
    return out


def plan(
    conn: Connection,
    message: str,
    facts: Sequence[Extracted],
    rels: Sequence[ExtractedRel],
    *,
    message_id: str,
    kind: str = "learning_run",
    actor: Actor = "pipeline",
) -> tuple[list[Extracted], list[ExtractedRel], PlanReport]:
    """The candidates of one message with the entity of each stated namesake planned
    (``EntityRef.ref_id`` + ``planned``). Creates the slot entities and their distinctions in
    one change set. Unchanged when the message states no namesakes."""
    report = PlanReport()
    st = stated(message)
    mine_f = [f for f in facts if f.message_id == message_id]
    mine_r = [r for r in rels if r.message_id == message_id]
    if not st:
        return list(facts), list(rels), report
    new_f = {id(f): f for f in mine_f}
    new_r = {id(r): r for r in mine_r}
    now_iso = utc_now_iso()
    with UnitOfWork(conn, kind=kind, actor=actor, summary="adaşlar", source_ref=message_id) as uow:
        for g in st.groups:
            report.groups += 1
            _plan_group(conn, uow, g, mine_f, mine_r, new_f, new_r, report, now_iso, message_id)
        for key in st.same:
            report.groups += 1
            _plan_same(conn, uow, key, mine_f, mine_r, new_f, new_r, report, now_iso)
    out_f = [new_f.get(id(f), f) for f in facts]
    out_r = [new_r.get(id(r), r) for r in rels]
    return out_f, out_r, report


def _planned(ref: EntityRef, entity_id: str) -> EntityRef:
    return replace(ref, ref_id=entity_id, planned=True)


def _assign(
    f_or_r: Extracted | ExtractedRel,
    end: str,
    entity_id: str,
    new_f: dict[int, Extracted],
    new_r: dict[int, ExtractedRel],
) -> None:
    if isinstance(f_or_r, Extracted):
        cur = new_f[id(f_or_r)]
        assert cur.candidate.entity is not None
        new_f[id(f_or_r)] = replace(
            cur, candidate=replace(cur.candidate, entity=_planned(cur.candidate.entity, entity_id))
        )
        return
    cur_r = new_r[id(f_or_r)]
    c = cur_r.candidate
    if end == "source":
        assert c.source is not None
        new_r[id(f_or_r)] = replace(
            cur_r, candidate=replace(c, source=_planned(c.source, entity_id))
        )
    else:
        assert c.target is not None
        new_r[id(f_or_r)] = replace(
            cur_r, candidate=replace(c, target=_planned(c.target, entity_id))
        )


def _unrelate(
    f_or_r: Extracted | ExtractedRel,
    end: str,
    new_f: dict[int, Extracted],
    new_r: dict[int, ExtractedRel],
) -> None:
    if isinstance(f_or_r, Extracted):
        cur = new_f[id(f_or_r)]
        assert cur.candidate.entity is not None
        ref = replace(cur.candidate.entity, relation=None)
        new_f[id(f_or_r)] = replace(cur, candidate=replace(cur.candidate, entity=ref))
        return
    cur_r = new_r[id(f_or_r)]
    c = cur_r.candidate
    if end == "source" and c.source is not None:
        c = replace(c, source=replace(c.source, relation=None))
    elif end == "target":
        c = replace(c, target=replace(c.target, relation=None))
    new_r[id(f_or_r)] = replace(cur_r, candidate=c)


def _about(
    key: str, facts: Sequence[Extracted], rels: Sequence[ExtractedRel]
) -> list[tuple[Extracted | ExtractedRel, str, EntityRef]]:
    out: list[tuple[Extracted | ExtractedRel, str, EntityRef]] = []
    for f in facts:
        for end, ref in _refs(f, None):
            if text.name_key(ref.name) == key:
                out.append((f, end, ref))
    for r in rels:
        for end, ref in _refs(None, r):
            if text.name_key(ref.name) == key:
                out.append((r, end, ref))
    return out


def _plan_group(
    conn: Connection,
    uow: UnitOfWork,
    g: Group,
    facts: Sequence[Extracted],
    rels: Sequence[ExtractedRel],
    new_f: dict[int, Extracted],
    new_r: dict[int, ExtractedRel],
    report: PlanReport,
    now: str,
    message_id: str,
) -> None:
    about = _about(g.key, facts, rels)
    slots = list(g.slots)
    if not slots:
        # The slots could not be read: the candidates' own descriptors (a relationship type,
        # the relation label, a single value) stand in, when there are not more of them than
        # people counted.
        seen: dict[str, Slot] = {}
        for item, end, ref in about:
            s = _descriptor(item, end, ref, g.key)
            if s is not None and s.words not in seen:
                seen[s.words] = s
        if not seen or len(seen) > g.count:
            report.unassigned += len(about)
            return
        slots = list(seen.values())
    ids: list[str | None] = []
    used: set[str] = set()
    for s in slots:
        found = [e for e in _existing_for(conn, g.key, s) if e not in used]
        if len(found) > 1:
            ids.append(None)  # several stored namesakes fit these words: the resolver asks
            continue
        if found:
            ids.append(found[0])
            used.add(found[0])
            continue
        ent = repo.insert_entity(
            conn, kind="person", name=g.name, relation=s.label,
            description=None if s.label else s.surface, now=now,
        )  # fmt: skip
        uow.record("memory_entities", ent.id, "create", None)
        report.entities_created.append(ent.id)
        ids.append(ent.id)
        used.add(ent.id)
        if s.type is not None:
            from lazis.memory import relationships

            relationships.ensure_user_relation(
                conn, uow, ent.id, s.surface, now=now, source_type="message",
                source_ref=message_id, quote=s.surface,
            )  # fmt: skip
    # The user said they are different people: never merged, never mixed up.
    known = [i for i in ids if i is not None]
    for a_i, a in enumerate(known):
        for b in known[a_i + 1 :]:
            if not gs.are_distinct(conn, a, b):
                gs.add_distinction(conn, a, b, now)
                report.distinctions += 1
    for item, end, ref in about:
        idx = _slot_index(item, end, ref, slots, g.key)
        if idx is None or ids[idx] is None:
            report.unassigned += 1
            if idx is None and g.slots and ref.relation:
                # The model's relation words disagree with the user's (Phase 9.1): not
                # trusted, so the resolver sees the namesakes and asks instead of picking.
                _unrelate(item, end, new_f, new_r)
            continue
        target = ids[idx]
        assert target is not None
        _assign(item, end, target, new_f, new_r)
        report.assigned += 1


def _descriptor(item: Extracted | ExtractedRel, end: str, ref: EntityRef, key: str) -> Slot | None:
    if isinstance(item, ExtractedRel):
        if _with_user(item, end):
            t = relations.TYPES.get(item.candidate.type)
            if t is not None:
                return Slot(words=f"type:{t.key}", surface=t.label, type=t.key, label=t.label)
        return None
    if ref.relation:
        s = slot_of(ref.relation, key)
        if s is not None:
            return s
    c = item.candidate
    if c.predicate in ("occupation", "employer", "location"):
        return Slot(words=text.fold(c.value), surface=c.value, type=None, label=None)
    return None


def _slot_index(
    item: Extracted | ExtractedRel, end: str, ref: EntityRef, slots: Sequence[Slot], key: str
) -> int | None:
    """The slot the user's words, the relation and the value each point to — only when those
    that point somewhere agree (Phase 9.1: whatever field the model chose, a fact never goes to
    a namesake its own words do not name)."""
    if isinstance(item, ExtractedRel):
        c = item.candidate
        type_key = c.type if _with_user(item, end) else None
        signals = [_by_quote(slots, c.quote or ""), _by_type(slots, type_key)]
    else:
        c = item.candidate
        # The model's relation words choose only among the slots the item's own words name:
        # "Ahmet emekli oldu." given as the colleague's is the model's guess, not the user's.
        named = _named(slots, c.quote or "")
        by_rel = _by_relation(slots, ref.relation, key)
        signals = [_only(named), by_rel if by_rel in named else None, _by_value(slots, c.value)]
    found = {i for i in signals if i is not None}
    return found.pop() if len(found) == 1 else None


def _only(hits: Sequence[int]) -> int | None:
    return hits[0] if len(hits) == 1 else None


def _named(slots: Sequence[Slot], quote: str) -> list[int]:
    q = set(text.words(quote)) - _EMPTY
    return [i for i, s in enumerate(slots) if s.words and set(s.words.split()) <= q]


def _by_quote(slots: Sequence[Slot], quote: str) -> int | None:
    return _only(_named(slots, quote))


def _by_type(slots: Sequence[Slot], type_key: str | None) -> int | None:
    if type_key is None:
        return None
    return _only([i for i, s in enumerate(slots) if s.type == type_key])


def _by_relation(slots: Sequence[Slot], relation: str | None, key: str) -> int | None:
    """The candidate's relation words ("komşusu", "iş arkadaşı") against each slot's."""
    if not relation:
        return None
    own = slot_of(relation, key)
    if own is not None and own.type is not None:
        return _by_type(slots, own.type)
    return _only([i for i, s in enumerate(slots)
                  if s.label and resolver.relation_compatible(relation, s.label)])  # fmt: skip


def _by_value(slots: Sequence[Slot], value: str) -> int | None:
    """A value said of one slot only ("Biri komşum, mimar": "mimar"), or a slot that is the
    value itself ("biri öğretmen")."""
    v = set(text.words(value)) - _EMPTY
    if not v:
        return None
    return _only([i for i, s in enumerate(slots) if v & (set(s.words.split()) | set(s.extra))])


def _plan_same(
    conn: Connection,
    uow: UnitOfWork,
    key: str,
    facts: Sequence[Extracted],
    rels: Sequence[ExtractedRel],
    new_f: dict[int, Extracted],
    new_r: dict[int, ExtractedRel],
    report: PlanReport,
    now: str,
) -> None:
    """ "Ahmet hem komşum hem iş arkadaşım": every candidate about Ahmet is the same person —
    the one stored Ahmet, or a new one; with several stored, nothing is planned (asks)."""
    about = _about(key, facts, rels)
    if not about:
        return
    stored = [
        e for e in repo.find_entities(conn, key) if e.status == "active" and e.kind == "person"
    ]
    if len(stored) > 1:
        report.unassigned += len(about)
        return
    if stored:
        eid = stored[0].id
    else:
        first = about[0][2]
        ent = repo.insert_entity(conn, kind="person", name=first.name, relation=None,
                                 description=None, now=now)  # fmt: skip
        uow.record("memory_entities", ent.id, "create", None)
        report.entities_created.append(ent.id)
        eid = ent.id
    for item, end, _ref in about:
        _assign(item, end, eid, new_f, new_r)
        report.assigned += 1


def slot_index(
    item: Extracted | ExtractedRel, end: str, ref: EntityRef, slots: Sequence[Slot], key: str
) -> int | None:
    """Which of a counted name's slots a candidate is about (None: it fits no slot)."""
    return _slot_index(item, end, ref, slots, key)
