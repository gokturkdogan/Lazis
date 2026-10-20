"""Predicate registry: what a memory says, and how it behaves (MEMORY_ARCHITECTURE §4).

Cardinality drives contradiction handling: a ``single`` predicate has one current value per
subject (a new value needs an explicit change signal, otherwise the user is asked); a
``multi`` predicate accumulates values (near-duplicates are merged). ``sensitivity`` is the
floor for the predicate; detectors and the extractor can only raise it. ``pinned`` predicates
apply to every reply (communication preferences), so they are always in the memory context.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Cardinality = Literal["single", "multi"]
Sensitivity = Literal["normal", "personal", "sensitive"]
Kind = Literal[
    "profile", "preference", "fact", "event", "plan", "goal", "decision", "project", "note"
]
Subject = Literal["user", "person", "project", "other"]


@dataclass(frozen=True)
class Predicate:
    key: str
    label: str  # Turkish, shown in the UI and in the memory context
    kind: Kind
    cardinality: Cardinality
    sensitivity: Sensitivity = "normal"
    subjects: tuple[Subject, ...] = ("user", "person")
    pinned: bool = False
    dated: bool = False  # events, decisions, milestones: the time is part of the fact


_P = Predicate
PREDICATES: dict[str, Predicate] = {
    p.key: p
    for p in (
        _P(
            "preferred_name",
            "hitap / tercih edilen ad",
            "profile",
            "single",
            subjects=("user", "person"),
            pinned=True,
        ),
        _P("occupation", "meslek", "profile", "single"),
        _P("employer", "çalıştığı yer", "profile", "single", "personal"),
        _P("location", "yaşadığı yer (şehir)", "profile", "single", "personal"),
        _P("computer", "kullandığı bilgisayar", "profile", "single", subjects=("user",)),
        _P("phone", "kullandığı telefon", "profile", "single", subjects=("user",)),
        _P("device", "diğer cihazlar", "profile", "multi", subjects=("user",)),
        _P("operating_system", "işletim sistemi", "profile", "multi", subjects=("user",)),
        _P("technology", "kullandığı teknoloji / dil / araç", "profile", "multi"),
        _P("skill", "beceri", "profile", "multi"),
        _P("language", "konuştuğu dil", "profile", "multi"),
        _P("interest", "ilgi alanı", "preference", "multi"),
        _P("likes", "sevdiği şey", "preference", "multi"),
        _P("dislikes", "sevmediği şey", "preference", "multi"),
        _P(
            "communication_preference",
            "iletişim tercihi",
            "preference",
            "multi",
            subjects=("user",),
            pinned=True,
        ),
        _P("work_preference", "çalışma tercihi", "preference", "multi", subjects=("user",)),
        _P("habit", "alışkanlık", "preference", "multi"),
        _P("goal", "hedef", "goal", "multi"),
        _P("plan", "plan / niyet", "plan", "multi", dated=True),
        _P("event", "olay / deneyim", "event", "multi", dated=True),
        _P("decision", "karar", "decision", "multi", dated=True),
        _P("birthday", "doğum günü", "profile", "single", "personal"),
        _P("family", "aile bilgisi", "fact", "multi", "personal"),
        _P("health", "sağlık bilgisi", "fact", "multi", "sensitive"),
        _P("finance", "finansal bilgi", "fact", "multi", "sensitive"),
        _P("contact", "iletişim bilgisi", "fact", "multi", "sensitive"),
        _P("address", "açık adres", "fact", "single", "sensitive"),
        _P("note", "not", "note", "multi", subjects=("user", "person", "project", "other")),
        # Projects (the subject is a project entity).
        _P("project_description", "proje açıklaması", "project", "single", subjects=("project",)),
        _P("project_goal", "proje amacı", "project", "multi", subjects=("project",)),
        _P(
            "project_status", "proje durumu", "project", "single", subjects=("project",), dated=True
        ),
        _P(
            "project_technology",
            "projede kullanılan teknoloji",
            "project",
            "multi",
            subjects=("project",),
        ),
        _P(
            "project_decision",
            "proje kararı",
            "decision",
            "multi",
            subjects=("project",),
            dated=True,
        ),
        _P(
            "project_milestone",
            "proje kilometre taşı",
            "event",
            "multi",
            subjects=("project",),
            dated=True,
        ),
        _P("project_person", "projedeki kişi", "project", "multi", subjects=("project",)),
    )
}


# Search words indexed (low-weighted) with every record of a predicate: the Turkish words people
# use when they ask about it ("nerede yaşıyorum" → location). Prefix search alone cannot bridge
# vowel narrowing ("yaşa-" → "yaşıyor") or synonyms. Specific words only: a generic verb
# ("çalışır", "kullanıyor") would match unrelated questions.
HINTS: dict[str, str] = {
    "preferred_name": "adım ad isim hitap seslen",
    "occupation": "meslek mesleği işi görevi",
    "employer": "şirket firma işyeri çalıştığı yer",
    "location": "şehir yaşıyor yaşadığı oturuyor nerede ikamet memleket",
    "computer": "bilgisayar laptop dizüstü makine ram bellek işlemci",
    "phone": "telefon cep",
    "device": "cihaz alet",
    "operating_system": "işletim sistemi",
    "technology": "teknoloji programlama",
    "skill": "beceri yetenek",
    "language": "dil konuşuyor",
    "interest": "ilgi hobi merak",
    "likes": "seviyor sever hoşlanır",
    "dislikes": "sevmiyor sevmez hoşlanmaz",
    "communication_preference": "yanıt cevap üslup konuşma",
    "work_preference": "verimli mesai",
    "habit": "alışkanlık",
    "goal": "hedef amaç",
    "plan": "plan niyet",
    "event": "olay deneyim",
    "decision": "karar",
    "birthday": "doğum günü doğdu yaş",
    "family": "aile anne baba kardeş eş çocuk kızı oğlu",
    "health": "sağlık hastalık",
    "finance": "para borç maaş",
    "contact": "numara telefon e-posta iletişim",
    "address": "adres ev",
    "project_description": "proje",
    "project_goal": "proje amaç",
    "project_status": "proje durum aşama",
    "project_technology": "proje teknoloji",
    "project_decision": "proje karar",
    "project_milestone": "proje sürüm",
    "project_person": "proje ekip kim",
}


def get(key: str) -> Predicate | None:
    return PREDICATES.get(key)


def keys() -> list[str]:
    return list(PREDICATES)


def describe_for_prompt() -> str:
    """One line per predicate for the extraction prompt (key — label · cardinality)."""
    lines: list[str] = []
    for p in PREDICATES.values():
        card = "tek değer" if p.cardinality == "single" else "çok değer"
        lines.append(f"- {p.key}: {p.label} ({card})")
    return "\n".join(lines)
