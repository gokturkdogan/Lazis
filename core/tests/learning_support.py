"""Helpers for the Phase 9 learning tests: a scripted model that answers per message (and per
focused re-read of a list), a conversation run through the production engine, and the memory
state read back from the database. Synthetic data only."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lazis.memory import graphstore as gs
from lazis.memory import repository as repo
from lazis.providers.llm.ports import ChatRequest
from lazis.storage import StorageHandle
from tests.conversation_support import ScriptedLLM, make_engine, run_turn

_TARGET = re.compile(r"^\[(m\d+)\] «(.*)»$", re.M | re.S)


def item(quote: str, predicate: str, value: str, *, entity: str = "", relation: str = "",
         statement: str = "", change: bool = False, certain: bool = True,
         importance: float = 0.7, tag: str = "m1") -> dict[str, Any]:  # fmt: skip
    return {"message": tag, "quote": quote, "entity": entity, "relation": relation,
            "predicate": predicate, "value": value, "statement": statement or f"{value}.",
            "change": change, "replaces": "", "certain": certain, "sensitive": "",
            "importance": importance}  # fmt: skip


def rel(quote: str, source: str, type_: str, target: str, *, status: str = "active",
        change: bool = False, tag: str = "m1", target_relation: str = "") -> dict[str, Any]:  # fmt: skip
    return {"message": tag, "quote": quote, "source": source, "source_relation": "",
            "type": type_, "target": target, "target_relation": target_relation,
            "statement": f"{source or 'Kullanıcı'} {type_} {target}.", "negated": False,
            "correction": False, "change": change, "status": status, "time": "",
            "certain": True}  # fmt: skip


Answer = tuple[list[dict[str, Any]], list[dict[str, Any]]]


@dataclass
class Brain:
    """message text → the model's answer; ``again``: text → the answer to a list re-read."""

    answers: dict[str, Answer] = field(default_factory=dict[str, Answer])
    again: dict[str, Answer] = field(default_factory=dict[str, Answer])
    raw: dict[str, str] = field(default_factory=dict[str, str])  # text → a broken answer
    reads: list[str] = field(default_factory=list[str])

    def __call__(self, request: ChatRequest) -> str:
        content = request.messages[-1].content
        found = _TARGET.findall(content.split("İncelenecek kullanıcı mesajları:")[-1])
        relist = "EKSİK LİSTE" in content
        items: list[dict[str, Any]] = []
        rels: list[dict[str, Any]] = []
        for tag, body in found:
            body = body.strip()
            self.reads.append(("again:" if relist else "") + body)
            if not relist and body in self.raw:
                return self.raw[body]
            src = self.again if relist else self.answers
            got = src.get(body)
            if got is None:
                continue
            items += [{**i, "message": tag} for i in got[0]]
            rels += [{**r, "message": tag} for r in got[1]]
        return json.dumps({"items": items, "relations": rels}, ensure_ascii=False)


@dataclass
class State:
    facts: list[dict[str, Any]]
    relationships: list[dict[str, Any]]
    entities: list[dict[str, Any]]
    inbox: list[dict[str, Any]]

    def has(self, who: str, predicate: str, value: str, status: str = "active") -> bool:
        return any(f["who"] == who and f["predicate"] == predicate and f["value"] == value
                   and f["status"] == status for f in self.facts)  # fmt: skip

    def values(self, who: str, predicate: str, status: str = "active") -> set[str]:
        return {f["value"] for f in self.facts if f["who"] == who and f["predicate"] == predicate
                and f["status"] == status}  # fmt: skip

    def rel(self, source: str, type_: str, target: str, status: str = "active") -> bool:
        return any(r["source"] == source and r["type"] == type_ and r["target"] == target
                   and r["status"] == status for r in self.relationships)  # fmt: skip

    def named(self, name: str) -> list[dict[str, Any]]:
        return [e for e in self.entities if e["name"] == name]


def state(storage: StorageHandle) -> State:
    def read(c: Any) -> State:
        ents = {e.id: e for e in repo.list_entities(c, limit=10_000)}
        facts = []
        for m in repo.list_memories(c, status=None, limit=10_000):
            e = ents.get(m.subject_id) if m.subject_id else None
            facts.append({"id": m.id, "who": e.name if e else "user", "subject_id": m.subject_id,
                          "predicate": m.predicate,
                          "value": m.value, "status": m.status, "content": m.content,
                          "event_time": m.event_time, "confidence": m.confidence,
                          "sources": repo.independent_sources(c, m.id),
                          "evidence": len(repo.evidence_for(c, m.id))})  # fmt: skip
        rels = []
        for r in gs.list_relationships(c, limit=10_000):
            a, b = ents.get(r.source_id), ents.get(r.target_id)
            rels.append({"source": a.name if a else "user", "type": r.type,
                         "target": b.name if b else "user", "status": r.status,
                         "source_id": r.source_id, "target_id": r.target_id})  # fmt: skip
        inbox = [{"type": i.type, "summary": i.summary} for i in repo.list_inbox(c, status="open")]
        return State(facts, rels,
                     [{"id": e.id, "name": e.name, "relation": e.relation} for e in ents.values()],
                     inbox)  # fmt: skip

    return storage.db.run_sync(read)


async def _settle(engine: Any) -> None:
    for _ in range(600):
        await asyncio.sleep(0.01)
        if engine.scheduler.background is None and not engine._learn and not engine.is_busy():  # pyright: ignore[reportPrivateUsage]
            return


def converse(tmp_path: Path, storage: StorageHandle, turns: Sequence[str], brain: Brain,
             *, between: Callable[[int], None] | None = None) -> State:  # fmt: skip
    """Each turn, then learning to the end (one job per turn)."""
    llm = ScriptedLLM(memory=brain)
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> None:
        cid = None
        for i, t in enumerate(turns):
            _, cid = await run_turn(engine, t, cid)
            await _settle(engine)
            if between is not None:
                between(i)
        await engine.close()

    asyncio.run(go())
    return state(storage)
