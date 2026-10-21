"""The personal profile file in JSON (Phase 8, ADR-0019): schema 1.0, mapped deterministically.

Every part is optional; values are strings, numbers, or lists of them::

    {
      "schema_version": "1.0",
      "profile":       {"preferred_name": "Kerem", "occupation": "analist", "location": "İzmir"},
      "people":        [{"id": "ahmet-komsu", "name": "Ahmet", "relation": "komşum",
                         "aliases": ["Ahmo"], "facts": {"occupation": "mimar"}, "notes": ["…"]},
                        {"id": "ahmet-is", "name": "Ahmet", "relation": "iş arkadaşım"}],
      "relationships": [{"from": "ahmet-komsu", "type": "sibling", "to": "mehmet"},
                        {"from": "user", "type": "kuzenim", "to": "elif"}],
      "projects":      [{"id": "atlas", "name": "Atlas", "description": "not uygulaması",
                         "status": "geliştiriliyor", "technologies": ["Python", "Rust"],
                         "people": ["can"]}],
      "preferences":   ["şekersiz kahve", {"kind": "dislikes", "value": "korku filmleri"}],
      "habits":        ["sabah 6'da kalkarım"],
      "goals":         [{"value": "maraton koşmak", "deadline": "2027"}],
      "events":        [{"text": "İzmir'e taşındım", "date": "2024"}],
      "facts":         [{"about": "ahmet-komsu", "predicate": "birthday", "value": "5 Mayıs"},
                        {"about": "user", "predicate": "location", "value": "İzmir",
                         "since": "2024"},
                        "Annemin bahçesinde iki kedi var."]
    }

``id`` is file-local: it keeps two people with one name apart ("ahmet-komsu", "ahmet-is").
Keys of ``profile`` and ``facts`` are predicate keys (``GET /memory/predicates``) or their
Turkish names below. The Phase 6 shape (``user``, ``people``, ``projects``) is read too.

The content is untrusted: values are data; nothing in it can approve, write or change a rule.
"""

from __future__ import annotations

import json
from typing import Any, cast

from lazis.bootstrap.proposals import (
    USER,
    Proposals,
    ProposedFact,
    ProposedPerson,
    ProposedRelation,
    category_for,
    label_of,
)
from lazis.memory import registry, relations, text

SCHEMA_VERSION = "1.0"
MAX_VALUE = 200
MAX_ITEMS = 2_000

# Turkish and English names for predicate keys (keys themselves always work).
ALIASES = {
    "ad": "preferred_name", "isim": "preferred_name", "name": "preferred_name",
    "hitap": "preferred_name", "meslek": "occupation", "is": "occupation", "job": "occupation",
    "isyeri": "employer", "sirket": "employer", "company": "employer", "sehir": "location",
    "city": "location", "yasadigi_yer": "location", "dogum_gunu": "birthday",
    "diller": "language", "languages": "language", "teknolojiler": "technology",
    "technologies": "technology", "beceriler": "skill", "skills": "skill",
    "bilgisayar": "computer", "telefon": "phone", "cihazlar": "device", "devices": "device",
    "ilgi_alanlari": "interest", "interests": "interest", "sevdikleri": "likes",
    "sevmedikleri": "dislikes", "iletisim_tercihleri": "communication_preference",
    "calisma_tercihleri": "work_preference", "aliskanliklar": "habit", "habits": "habit",
    "hedefler": "goal", "goals": "goal", "planlar": "plan", "notlar": "note", "notes": "note",
    "aile": "family", "family": "family",
}  # fmt: skip
_USER_REFS = frozenset({"user", "ben", "kullanici", "me", "kendim"})
_PREFERENCE_KINDS = frozenset({"likes", "dislikes", "interest", "communication_preference",
                               "work_preference"})  # fmt: skip


class ProfileError(ValueError):
    def __init__(self, code: str, detail: str = "", *, line: int | None = None,
                 column: int | None = None) -> None:  # fmt: skip
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail
        self.line = line  # where an invalid JSON file breaks (shown to the user)
        self.column = column


def predicate_for(key: str) -> str | None:
    k = key.strip()
    if registry.get(k) is not None:
        return k
    folded = "_".join(text.words(k))
    mapped = ALIASES.get(folded)
    return mapped if mapped is not None and registry.get(mapped) is not None else None


def _values(raw: Any) -> list[str]:
    if isinstance(raw, bool) or raw is None:
        return []
    if isinstance(raw, str | int | float):
        v = str(raw).strip()
        return [v[:MAX_VALUE]] if v else []
    if isinstance(raw, list):
        out: list[str] = []
        for v in cast(list[Any], raw):
            out += _values(v) if not isinstance(v, list) else []
        return out
    return []


def relation_type(words: str) -> str | None:
    """A relationship type from a key ("sibling") or the user's words ("kuzenim", "komşusu")."""
    w = words.strip()
    if w in relations.TYPES:
        return w
    return relations.lexicon(w)


class _Mapper:
    def __init__(self, raw_text: str) -> None:
        self.raw = raw_text
        self.out = Proposals()
        self.by_id: dict[str, str] = {}  # file id → person key
        self.by_name: dict[str, list[str]] = {}  # name key → person keys
        self._pos = 0

    # -- traceability: the file line where a value is written (search forward, then anywhere)
    def line(self, value: str) -> int | None:
        needle = json.dumps(value, ensure_ascii=False)[1:-1]
        i = self.raw.find(needle, self._pos)
        if i < 0:
            i = self.raw.find(needle)
        if i < 0:
            return None
        self._pos = i + len(needle)
        return self.raw.count("\n", 0, i) + 1

    def warn(self, path: str, code: str) -> None:
        self.out.warnings.append(f"{path}: {code}")

    def person(self, name: str, *, kind: str, relation: str | None, description: str | None,
               aliases: tuple[str, ...], section: str, file_id: str | None) -> str:  # fmt: skip
        key = f"p{len(self.out.people) + 1}"
        label = None
        if relation:
            t = relation_type(relation)
            label = relations.TYPES[t].label if t else relation.strip()[:80]
        self.out.people.append(ProposedPerson(key, name, kind, label, description, aliases,
                                              section, excerpt=name))  # fmt: skip
        if file_id:
            self.by_id[file_id] = key
        self.by_name.setdefault(text.name_key(name), []).append(key)
        return key

    def ref(self, raw: Any, path: str) -> str | None:
        """A person reference: "user", a file id, or a name (unique in the file, else new)."""
        if not isinstance(raw, str | int) or not str(raw).strip():
            self.warn(path, "missing_reference")
            return None
        r = str(raw).strip()
        if text.fold(r) in _USER_REFS:
            return USER
        if r in self.by_id:
            return self.by_id[r]
        keys = self.by_name.get(text.name_key(r), [])
        if len(keys) == 1:
            return keys[0]
        if len(keys) > 1:
            self.warn(path, "ambiguous_reference")  # two people with that name: use their ids
            return None
        if not r[:1].isupper():
            self.warn(path, "unknown_reference")
            return None
        return self.person(r, kind="person", relation=None, description=None, aliases=(),
                           section=path, file_id=None)  # fmt: skip

    def fact(self, subject: str, predicate: str, value: str, path: str, *,
             time: str | None = None) -> None:  # fmt: skip
        p = self.out.person(subject) if subject != USER else None
        who = "Kullanıcı" if p is None else (f"{p.name} ({p.relation})" if p.relation else p.name)
        kind = "person" if p is None else p.kind
        if registry.PREDICATES[predicate].subjects == ("project",) and kind != "project":
            self.warn(path, "project_predicate_for_a_person")
            return
        if kind == "project" and "project" not in registry.PREDICATES[predicate].subjects:
            self.warn(path, "predicate_not_for_a_project")
            return
        if len(self.out.facts) >= MAX_ITEMS:
            raise ProfileError("too_many_items")
        self.out.facts.append(ProposedFact(
            subject=subject, predicate=predicate, value=value,
            statement=f"{who} — {label_of(predicate)}: {value}", method="json",
            category=category_for(predicate, subject == USER, kind), time=time,
            section=path, excerpt=value, line=self.line(value),
        ))  # fmt: skip

    def facts(self, subject: str, raw: Any, path: str) -> None:
        if raw is None:
            return
        if not isinstance(raw, dict):
            self.warn(path, "not_an_object")
            return
        for key, val in cast(dict[str, Any], raw).items():
            pred = predicate_for(str(key))
            if pred is None:
                self.warn(f"{path}.{key}", "unknown_field")
                continue
            for v in _values(val):
                self.fact(subject, pred, v, f"{path}.{key}")

    def relation(
        self,
        source: str,
        type_key: str,
        target: str,
        path: str,
        *,
        status: str = "active",
        time: str | None = None,
        excerpt: str = "",
    ) -> None:
        if source == target:
            self.warn(path, "self_relation")
            return
        t = relations.TYPES[type_key]
        st = status if status in ("active", "ended", "planned") else "active"
        names = {k: (self.out.person(k).name if self.out.person(k) else "Kullanıcı")  # type: ignore[union-attr]
                 for k in (source, target)}  # fmt: skip
        self.out.relations.append(ProposedRelation(
            source=source, type=type_key, target=target, method="json", status=st,  # type: ignore[arg-type]
            time=time, statement=relations.describe(names[source], type_key, names[target]),
            section=path, excerpt=excerpt or t.label, line=self.line(excerpt) if excerpt else None,
        ))  # fmt: skip


def parse(raw_text: str) -> Proposals:
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ProfileError(
            "invalid_json",
            f"satır {exc.lineno}, sütun {exc.colno}",
            line=exc.lineno,
            column=exc.colno,
        ) from None
    if not isinstance(data, dict):
        raise ProfileError("not_an_object")
    d = cast(dict[str, Any], data)
    version = d.get("schema_version")
    if version is not None and str(version).split(".")[0] != SCHEMA_VERSION.split(".")[0]:
        raise ProfileError("unsupported_schema", str(version)[:20])
    m = _Mapper(raw_text)
    known = {"schema_version", "profile", "user", "people", "relationships", "projects",
             "preferences", "habits", "goals", "events", "facts"}  # fmt: skip
    for key in d:
        if key not in known:
            m.warn(key, "unknown_section")
    m.facts(USER, d.get("profile", d.get("user")), "profile")

    # People and projects first: relationships and facts refer to them.
    for group, kind in (("people", "person"), ("projects", "project")):
        entries = d.get(group)
        if entries is None:
            continue
        if not isinstance(entries, list):
            m.warn(group, "not_a_list")
            continue
        for i, entry in enumerate(cast(list[Any], entries)):
            path = f"{group}[{i}]"
            if not isinstance(entry, dict):
                m.warn(path, "not_an_object")
                continue
            e = cast(dict[str, Any], entry)
            name = str(e.get("name", "")).strip()[:80]
            if not text.name_key(name):
                m.warn(path, "missing_name")
                continue
            relation = str(e.get("relation", "")).strip()[:80] or None
            desc = str(e.get("description", "")).strip()[:MAX_VALUE] or None
            aliases = tuple(_values(e.get("aliases")))[:10]
            file_id = str(e["id"]).strip() if isinstance(e.get("id"), str | int) else None
            pkind = str(e.get("kind", kind)) if kind == "person" else kind
            key = m.person(name, kind=pkind if pkind in ("person", "organization", "place",
                                                         "project", "group", "event") else kind,
                           relation=relation, description=desc, aliases=aliases,
                           section=f"{path} ({name})", file_id=file_id)  # fmt: skip
            if relation and kind == "person":
                t = relation_type(relation)
                if t is not None:
                    m.relation(USER, t, key, f"{path}.relation", excerpt=relation)
                else:
                    m.warn(f"{path}.relation", "unknown_relation_kept_as_label")
            m.facts(key, e.get("facts"), f"{path}.facts")
            for n in _values(e.get("notes")):
                m.fact(key, "note", n, f"{path}.notes")
            if kind == "project":
                for field_name, pred in (("description", "project_description"),
                                         ("status", "project_status"), ("technologies",
                                         "project_technology"), ("goals", "project_goal"),
                                         ("decisions", "project_decision"),
                                         ("milestones", "project_milestone")):  # fmt: skip
                    for v in _values(e.get(field_name)):
                        m.fact(key, pred, v, f"{path}.{field_name}")
                mine = str(e.get("role", "")).strip()
                m.relation(USER, "develops" if not mine else (relation_type(mine) or "works_on"),
                           key, f"{path}", excerpt=name)  # fmt: skip

    # Project members after all people exist.
    for i, entry in enumerate(cast(list[Any], d.get("projects") or [])):
        if not isinstance(entry, dict):
            continue
        e = cast(dict[str, Any], entry)
        proj = m.by_id.get(str(e.get("id", ""))) or next(
            iter(m.by_name.get(text.name_key(str(e.get("name", ""))), [])), None
        )
        for j, who in enumerate(cast(list[Any], e.get("people") or [])):
            ref = m.ref(who, f"projects[{i}].people[{j}]")
            if ref is not None and proj is not None:
                m.relation(ref, "works_on", proj, f"projects[{i}].people[{j}]",
                           excerpt=str(who))  # fmt: skip

    rels = d.get("relationships")
    if rels is not None and not isinstance(rels, list):
        m.warn("relationships", "not_a_list")
        rels = []
    for i, entry in enumerate(cast(list[Any], rels or [])):
        path = f"relationships[{i}]"
        if not isinstance(entry, dict):
            m.warn(path, "not_an_object")
            continue
        e = cast(dict[str, Any], entry)
        t = relation_type(str(e.get("type", "")))
        if t is None:
            m.warn(f"{path}.type", "unknown_relation")
            continue
        src, tgt = m.ref(e.get("from"), f"{path}.from"), m.ref(e.get("to"), f"{path}.to")
        if src is None or tgt is None:
            continue
        m.relation(src, t, tgt, path, status=str(e.get("status", "active")),
                   time=str(e["since"]) if e.get("since") else None,
                   excerpt=str(e.get("type", "")))  # fmt: skip

    simple = (("habits", "habit"), ("goals", "goal"), ("events", "event"))
    prefs = d.get("preferences")
    for i, entry in enumerate(cast(list[Any], prefs if isinstance(prefs, list) else [])):
        path = f"preferences[{i}]"
        if isinstance(entry, dict):
            e = cast(dict[str, Any], entry)
            kind_raw = str(e.get("kind", "likes"))
            kind = predicate_for(kind_raw) or kind_raw
            for v in _values(e.get("value")):
                m.fact(USER, kind if kind in _PREFERENCE_KINDS else "likes", v, path)
        else:
            for v in _values(entry):
                m.fact(USER, "likes", v, path)
    for group, pred in simple:
        entries = d.get(group)
        for i, entry in enumerate(cast(list[Any], entries if isinstance(entries, list) else [])):
            path = f"{group}[{i}]"
            if isinstance(entry, dict):
                e = cast(dict[str, Any], entry)
                when = e.get("date") or e.get("deadline") or e.get("time")
                for v in _values(e.get("value") or e.get("text")):
                    m.fact(USER, pred, v, path, time=str(when)[:40] if when else None)
            else:
                for v in _values(entry):
                    m.fact(USER, pred, v, path)
    facts = d.get("facts")
    for i, entry in enumerate(cast(list[Any], facts if isinstance(facts, list) else [])):
        path = f"facts[{i}]"
        if isinstance(entry, dict):
            e = cast(dict[str, Any], entry)
            about = m.ref(e.get("about", "user"), f"{path}.about")
            pred = predicate_for(str(e.get("predicate", "note")))
            if about is None or pred is None:
                if pred is None:
                    m.warn(f"{path}.predicate", "unknown_field")
                continue
            when = e.get("since") or e.get("date") or e.get("time")  # a change with its time
            for v in _values(e.get("value")):
                m.fact(about, pred, v, path, time=str(when)[:40] if when else None)
        else:
            for v in _values(entry):
                m.fact(USER, "note", v, path)
    return m.out
