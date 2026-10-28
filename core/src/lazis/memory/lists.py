"""Lists in the user's words, and whether the model read all of them (Phase 9).

"Ahmet'in iki kardeşi var: Mehmet ve Ali." — the model sometimes writes Ahmet → sibling →
Mehmet and stops. Nothing here makes a relationship or a fact: this module only **finds**
lists ("Mehmet ve Ali", "Ayşe, Fatma ve Zeynep", "İstanbul, Ankara ve İzmir'de",
"satranç, yüzme ve dalış") and a stated count ("iki kardeşi", "üç projem"), and compares
them with what the model extracted:

* a list some of whose members were extracted and some not is a **gap** — the learning job
  asks the model again about the missing members only (:func:`completion_note`), and keeps
  only answers about those members, validated like any other;
* a stated count that differs from the names given is a **count mismatch** — kept as the
  user's own words ("üç kardeşi var: Mehmet ve Ali"), never filled with invented people.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from lazis.memory import text
from lazis.memory.extraction import Extracted, ExtractedRel
from lazis.memory.models import Candidate, EntityRef

_NUMBERS = {"iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6, "yedi": 7, "sekiz": 8,
            "dokuz": 9, "on": 10}  # fmt: skip
# A list item: a capitalised name (one or two words, an apostrophe suffix allowed on the last)
# or a short lowercase phrase (one or two words).
_NAME = r"[A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ]+(?:\s[A-ZÇĞİÖŞÜ][\wçğıöşü]+)?(?:['’][a-zçğıöşü]+)?"
_PHRASE = r"(?<![\wçğıöşüÇĞİÖŞÜ])[A-Za-zçğıöşüÇĞİÖŞÜ][a-zçğıöşü]+(?:['’][a-zçğıöşü]+)?"
_LIST = re.compile(
    rf"(?P<items>(?:(?:{_NAME}),\s*)*(?:{_NAME})\s+(?:ve|ile|veya)\s+(?:{_NAME}))"
    rf"|(?P<low>(?:(?:{_PHRASE}),\s*)*(?:{_PHRASE})\s+(?:ve|veya)\s+(?:{_PHRASE}))"
)
_SPLIT = re.compile(r",\s*|\s+(?:ve|ile|veya)\s+")
_COUNT = re.compile(r"\b(iki|uc|dort|bes|alti|yedi|sekiz|dokuz|on|\d+)\s+(\w+)")


@dataclass(frozen=True)
class Enumeration:
    members: tuple[str, ...]  # as the user wrote them (suffix stripped)
    keys: tuple[str, ...]  # comparable keys
    count: int | None = None  # a number the user stated for it ("iki kardeşi")
    words: str = ""  # the user's words for the list ("iki kardeşi var: Mehmet ve Ali")


def _strip(item: str) -> str:
    return re.split(r"['’]", item.strip(), maxsplit=1)[0].strip()


def enumerations(message: str) -> list[Enumeration]:
    out: list[Enumeration] = []
    for m in _LIST.finditer(message):
        raw = m.group("items") or m.group("low") or ""
        members = [_strip(x) for x in _SPLIT.split(raw) if x.strip()]
        if len(members) < 2 or len(members) > 8:
            continue
        keys = tuple(text.name_key(x) for x in members)
        if len(set(keys)) != len(keys):
            continue
        # A count right before the list ("iki kardeşi var: …", "üç projem var: …").
        before = message[max(0, m.start() - 40) : m.start()]
        count: int | None = None
        span_start = m.start()
        for cm in _COUNT.finditer(text.fold(before)):
            n = cm.group(1)
            count = int(n) if n.isdigit() else _NUMBERS.get(n)
            span_start = max(0, m.start() - 40) + cm.start()
        words = message[span_start : m.end()].strip()
        out.append(Enumeration(tuple(members), keys, count, words))
    return out


def _mentions(e: Enumeration, key: str) -> bool:
    return key in e.keys


def _keys_in(value: str) -> set[str]:
    return {text.name_key(w) for w in re.split(r"[,\s]+(?:ve\s+)?", value) if w} | {
        text.name_key(value)
    }


def covered(e: Enumeration, facts: Sequence[Extracted], rels: Sequence[ExtractedRel]) -> set[str]:
    """Keys of the list's members the extraction says something about."""
    got: set[str] = set()
    for f in facts:
        c = f.candidate
        if c.entity is not None and _mentions(e, text.name_key(c.entity.name)):
            got.add(text.name_key(c.entity.name))
        for k in _keys_in(c.value):
            if _mentions(e, k):
                got.add(k)
    for r in rels:
        rc = r.candidate
        for end in (rc.source, rc.target):
            if end is not None and _mentions(e, text.name_key(end.name)):
                got.add(text.name_key(end.name))
    return got


@dataclass(frozen=True)
class Gap:
    message_id: str
    enumeration: Enumeration
    missing: tuple[str, ...]  # members as written
    found: tuple[str, ...]  # what was extracted for the others ("Ahmet → sibling → Mehmet")


def gaps(
    messages: dict[str, str], facts: Sequence[Extracted], rels: Sequence[ExtractedRel]
) -> list[Gap]:
    out: list[Gap] = []
    for mid, msg in messages.items():
        f = [x for x in facts if x.message_id == mid]
        r = [x for x in rels if x.message_id == mid]
        for e in enumerations(msg):
            got = covered(e, f, r)
            if not got or len(got) == len(e.keys):
                continue
            missing = tuple(m for m, k in zip(e.members, e.keys, strict=True) if k not in got)
            found = [_describe_rel(x) for x in r if _rel_touches(e, x)]
            found += [_describe_fact(x) for x in f if _fact_touches(e, x)]
            out.append(Gap(mid, e, missing, tuple(found[:4])))
    return out


def _rel_touches(e: Enumeration, r: ExtractedRel) -> bool:
    return any(end is not None and _mentions(e, text.name_key(end.name))
               for end in (r.candidate.source, r.candidate.target))  # fmt: skip


def _fact_touches(e: Enumeration, f: Extracted) -> bool:
    c = f.candidate
    return (c.entity is not None and _mentions(e, text.name_key(c.entity.name))) or any(
        _mentions(e, k) for k in _keys_in(c.value)
    )


def _describe_rel(r: ExtractedRel) -> str:
    rc = r.candidate
    return f"{rc.source.name if rc.source else 'kullanıcı'} → {rc.type} → {rc.target.name}"


def _describe_fact(f: Extracted) -> str:
    c = f.candidate
    who = c.entity.name if c.entity else "kullanıcı"
    return f"{who} — {c.predicate}: {c.value}"


def completion_note(gap: Gap) -> str:
    """The extra instruction for a second, focused read of one message."""
    listed = ", ".join(gap.enumeration.members)
    return (
        "EKSİK LİSTE ÖĞELERİ: Bu mesajda bir liste var: "
        f"«{listed}». Bunlardan biri ya da birkaçı için şu çıkarıldı: "
        f"{'; '.join(gap.found)}. Listede şu öğeler için hiçbir şey çıkarılmadı: "
        f"{', '.join(gap.missing)}. YALNIZCA bu eksik öğeler için, mesajın AÇIKÇA söylediği "
        "bilgi ve ilişkileri çıkar; aynı cümle yapısı onlar için de geçerliyse aynı türü kullan. "
        "Mesaj söylemiyorsa boş listeler döndür. Başka hiçbir şey çıkarma."
    )


def keep_only_missing(
    gap: Gap, facts: Sequence[Extracted], rels: Sequence[ExtractedRel]
) -> tuple[list[Extracted], list[ExtractedRel]]:
    """Of a second read, only what is about the missing members of that list."""
    missing = {text.name_key(m) for m in gap.missing}
    keep_f = [
        f for f in facts
        if f.message_id == gap.message_id and (
            (f.candidate.entity is not None and text.name_key(f.candidate.entity.name) in missing)
            or bool(_keys_in(f.candidate.value) & missing))
    ]  # fmt: skip
    keep_r = [
        r for r in rels
        if r.message_id == gap.message_id and any(
            end is not None and text.name_key(end.name) in missing
            for end in (r.candidate.source, r.candidate.target))
    ]  # fmt: skip
    return keep_f, keep_r


def count_notes(messages: dict[str, str], rels: Sequence[ExtractedRel]) -> list[Extracted]:
    """ "Ahmet'in üç kardeşi var: Mehmet ve Ali": two named, three said. The user's own words
    are kept as a note about the person whose relatives they are; nobody is invented."""
    out: list[Extracted] = []
    for mid, msg in messages.items():
        for e in enumerations(msg):
            if e.count is None or e.count == len(e.members):
                continue
            owners = {
                (r.candidate.source.name if r.candidate.source else None)
                for r in rels if r.message_id == mid and _rel_touches(e, r)
            }  # fmt: skip
            if len(owners) != 1:
                continue
            owner = next(iter(owners))
            named = " ve ".join(e.members)
            who = owner or "Kullanıcı"
            stmt = (f"{who} için {e.count} kişi söylendi; {len(e.members)} tanesinin adı "
                    f"biliniyor ({named}).")  # fmt: skip
            c = Candidate(
                predicate="note", value=e.words[:160], statement=stmt,
                about="user" if owner is None else "entity",
                entity=None if owner is None else EntityRef(owner),
                quote=e.words[:160], importance=0.5,
            )  # fmt: skip
            out.append(Extracted(mid, c))
    return out


def with_list_quote(e: Extracted, quote: str) -> Extracted:
    return replace(e, candidate=replace(e.candidate, quote=quote))
