"""How much a memory matters (Phase 9): five tiers, computed from what is stored — never a
reason to write on its own (the learning policy decides that; importance only orders and
prioritises: recall ties, the quality checks' order, the memory screen's badges).

* ``critical_personal`` — who the user is and their closest people: name, birthday, family,
  health and money (sensitive), anything the user asked to remember;
* ``high`` — the user's current life: work, city, goals, plans, projects, relationships;
* ``medium`` — preferences, habits, interests, facts about other people;
* ``low`` — notes and details the extraction itself rated low;
* ``ephemeral`` — a passing state ("bugün çok yorgunum"): not kept by background learning.

Repetition counts a little (independent sources move a ``medium`` fact to ``high``), but no
amount of repetition makes something ``critical_personal``.
"""

from __future__ import annotations

from typing import Literal

from lazis.memory import registry

Tier = Literal["critical_personal", "high", "medium", "low", "ephemeral"]
TIERS: tuple[Tier, ...] = ("critical_personal", "high", "medium", "low", "ephemeral")

_CRITICAL = frozenset({"preferred_name", "birthday", "family", "health", "finance", "contact",
                       "address", "relationship"})  # fmt: skip
_HIGH = frozenset({"occupation", "employer", "location", "goal", "plan", "decision",
                   "project_description", "project_goal", "project_status",
                   "project_technology", "project_decision", "project_milestone",
                   "project_person", "language", "skill", "computer", "phone"})  # fmt: skip
_EXPLICIT = frozenset({"requested", "user_edit", "confirmed"})


def tier(
    *,
    predicate: str,
    importance: float,
    origin: str = "stated",
    sensitivity: str = "normal",
    about_user: bool = True,
    sources: int = 1,
    durable: bool = True,
) -> Tier:
    if not durable:
        return "ephemeral"
    p = registry.get(predicate)
    if sensitivity == "sensitive" or (about_user and predicate in _CRITICAL):
        return "critical_personal"
    if origin in _EXPLICIT and about_user:
        return "critical_personal"
    if predicate in _HIGH and (about_user or predicate.startswith("project_")):
        return "high"
    if importance < 0.35 and predicate == "note":
        return "low"
    if p is not None and p.kind in ("preference", "fact") and sources >= 3:
        return "high"  # said again and again, in different messages
    if importance < 0.3:
        return "low"
    return "medium"


def rank(t: Tier) -> int:
    """0 = most important."""
    return TIERS.index(t)
