"""Phase 6 extraction gold set on the real runtime (production engine, synthetic data).

    uv run --project core python evals/runners/p6_extraction.py --model gemma4:12b-it-qat
    uv run --project core python evals/runners/p6_extraction.py --model qwen3.5:9b-q4_K_M --only C1,E5

Every case runs in its own throwaway encrypted database (random in-memory key): optional
history and seed memories, then one real turn through the production engine, then the
background learning job exactly as the app runs it (the model under test is made "trusted"
for the run). The outcome is read back from the memory tables (active memories, superseded
values, open inbox items) and scored against evals/datasets/memory_extraction_gold.json:

* recall: expected records found (right predicate group, subject, value term, outcome);
* false records: anything else saved or queued that the case does not allow;
* critical: a forbidden string stored (secrets, injected rules, LAZIS's guesses), a wrong
  predicate the case forbids, or a namesake attached without asking.

Writes evals/reports/phase6/extraction_<model>[_<label>].json (raw model JSON included: the
data is synthetic).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import shutil
import tempfile
import time
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from common import manifest

from lazis.config.model import (
    AppSection,
    ConversationSection,
    LoggingSection,
    MemorySection,
    ModelsSection,
    Settings,
    StorageSection,
)
from lazis.conversation import ConversationEngine, TurnRequest, repository
from lazis.conversation.prompts import time_note
from lazis.ids import utc_now_iso
from lazis.memory import repository as memory_repo
from lazis.memory import service, text
from lazis.memory.models import Candidate, EntityRef
from lazis.memory.service import Source
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import ChatRequest, GenerationDone, StreamEvent, TextDelta
from lazis.security.secrets import SecretBytes
from lazis.storage import StorageHandle, open_storage
from lazis.storage.unit_of_work import UnitOfWork

ROOT = Path(__file__).resolve().parents[1]
GOLD = ROOT / "datasets" / "memory_extraction_gold.json"
OUT = ROOT / "reports" / "phase6"


class Recorder:
    """The production provider, recording the extraction requests' raw output and timing."""

    def __init__(self, inner: OllamaProvider) -> None:
        self.inner = inner
        self.extractions: list[dict[str, Any]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        fmt = request.options.response_format
        is_x = isinstance(fmt, dict) and "items" in fmt.get("properties", {})
        raw, started = "", time.monotonic()
        async for ev in self.inner.stream(request):
            if is_x and isinstance(ev, TextDelta) and ev.kind == "content":
                raw += ev.text
            if is_x and isinstance(ev, GenerationDone):
                m = ev.metrics
                self.extractions.append({
                    "raw": raw, "prompt_tokens": m.prompt_tokens, "output_tokens": m.output_tokens,
                    "ttft_ms": None if m.ttft_ms is None else round(m.ttft_ms),
                    "total_ms": round((time.monotonic() - started) * 1000),
                    "messages": len(request.messages),
                })  # fmt: skip
            yield ev


def settings(root: Path, model: str) -> Settings:
    return Settings(
        app=AppSection(environment="test"),
        storage=StorageSection(data_dir=root / "data"),
        logging=LoggingSection(directory=root / "logs"),
        models=ModelsSection(max_output_tokens=200),
        conversation=ConversationSection(idle_compaction_delay_s=3600.0),
        memory=MemorySection(trusted_models=(model,)),
    )


def seed(storage: StorageHandle, case: dict[str, Any], session_id: str) -> None:
    now = utc_now_iso()
    note = time_note(datetime.now())

    def write(conn: repository.Connection) -> None:
        with repository.transaction(conn):
            for role, body in case.get("history", []):
                repository.insert_message(conn, conversation_id=session_id, role=role, content=body,
                                          status="complete", now=now,
                                          context_note=note if role == "user" else None)  # fmt: skip
        for s in case.get("seed", []):
            ent = s.get("entity")
            ref = None
            if ent:
                ref_id = None
                if s.get("new_entity"):
                    with UnitOfWork(conn, kind="import", actor="import", summary="seed") as _:
                        ref_id = memory_repo.insert_entity(conn, kind="person", name=ent["name"],
                                                           relation=ent.get("relation"), description=None,
                                                           now=now).id  # fmt: skip
                ref = EntityRef(ent["name"], relation=ent.get("relation"), ref_id=ref_id)
            c = Candidate(predicate=s["predicate"], value=s["value"], statement=s["statement"],
                          about="entity" if ref else "user", entity=ref, origin="imported")  # fmt: skip
            service.apply_candidates(conn, [c], source=Source("import"), explicit=True, actor="import")

    storage.db.run_sync(write)


def records(storage: StorageHandle) -> list[dict[str, Any]]:
    def read(conn: repository.Connection) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for status in ("active", "superseded"):
            for m in memory_repo.list_memories(conn, status=status, limit=500):
                e = memory_repo.get_entity(conn, m.subject_id) if m.subject_id else None
                out.append({"where": "memory", "status": status, "predicate": m.predicate,
                            "about": e.name if e else "user", "relation": e.relation if e else None,
                            "value": m.value, "statement": m.content, "origin": m.origin,
                            "sensitivity": m.sensitivity})  # fmt: skip
        # Phase 7: the user's relationships live in the graph (the `relationship` predicate is
        # no longer offered to the model); they count as `relationship` records here.
        from lazis.memory import graphstore, relations
        from lazis.memory.models import CURRENT, USER_ID

        for rel in graphstore.list_relationships(conn, statuses=CURRENT, limit=500):
            if USER_ID not in (rel.source_id, rel.target_id):
                continue
            other = memory_repo.get_entity(conn, rel.target_id if rel.source_id == USER_ID else rel.source_id)
            t = relations.TYPES.get(rel.type)
            if other is None or t is None:
                continue
            out.append({"where": "memory", "status": "active", "predicate": "relationship",
                        "about": other.name, "relation": other.relation, "value": t.label,
                        "statement": f"{other.name}: kullanıcının {t.label}", "origin": rel.origin,
                        "sensitivity": rel.sensitivity})  # fmt: skip
        for item in memory_repo.list_inbox(conn, status="open"):
            c = item.payload.get("candidate", {})
            ent = c.get("entity") or {}
            out.append({"where": "inbox", "status": item.type, "predicate": c.get("predicate"),
                        "about": ent.get("name") or "user", "relation": ent.get("relation"),
                        "value": c.get("value", ""), "statement": c.get("statement", "")})  # fmt: skip
        return out

    return storage.db.run_sync(read)


def _about_ok(expected: str, actual: str) -> bool:
    return expected == "any" or text.name_key(expected) == text.name_key(actual) or (
        expected == "user" and actual == "user"
    )


def score(case: dict[str, Any], recs: list[dict[str, Any]]) -> dict[str, Any]:
    seeded = {(s["predicate"], text.fold(s["value"])) for s in case.get("seed", [])}
    new = [r for r in recs if not (r["where"] == "memory" and (r["predicate"], text.fold(r["value"])) in seeded)]
    current = [r for r in new if r["status"] != "superseded"]
    matched: set[int] = set()
    found: list[bool] = []
    for exp in case["expect"]:
        hit = None
        for i, r in enumerate(current):
            body = text.fold(f"{r['value']} {r['statement']}")
            outcome = exp.get("outcome", "any")
            if (
                i not in matched
                and r["predicate"] in exp["predicates"]
                and _about_ok(exp["about"], r["about"])
                and any(v in body for v in exp["values"])
                and (outcome == "any" or outcome == r["where"])
            ):
                hit = i
                break
        found.append(hit is not None)
        if hit is not None:
            matched.add(hit)
    allowed = set(case.get("allow", []))
    false_records = [r for i, r in enumerate(current) if i not in matched and r["predicate"] not in allowed]
    critical: list[str] = []
    for r in recs:
        body = text.fold(f"{r['value']} {r['statement']}")
        for f in case.get("forbid", []):
            if text.fold(f) in body:
                critical.append(f"forbidden '{f}' in {r['where']}")
        for f in case.get("forbid_memory", []):
            if r["where"] == "memory" and text.fold(f) in body:
                critical.append(f"forbidden '{f}' in memory")
        if r["predicate"] in case.get("forbid_predicates", []):
            critical.append(f"forbidden predicate {r['predicate']}")
    for r in recs:
        if r["where"] != "memory" or "satranc" not in text.fold(r["value"] + r["statement"]):
            continue
        if case["id"] == "E5" and r["about"] != "user":
            critical.append("namesake attached without asking")
        elif case["id"] == "E5":
            false_records.append(r)  # about Ahmet, stored as a fact about the user
    superseded = [r["value"] for r in recs if r["status"] == "superseded"]
    for v in case.get("superseded", []):
        if not any(text.fold(v) in text.fold(s) for s in superseded):
            found.append(False)  # the old value should have been replaced (history kept)
    for v in case.get("kept", []):
        if not any(r["status"] == "active" and text.fold(v) in text.fold(r["value"]) for r in recs):
            critical.append(f"'{v}' should have stayed current")
    return {
        "expected": len(found),
        "found": sum(found),
        "false_records": len(false_records),
        "false_detail": [f"{r['where']}:{r['predicate']}:{r['about']}:{r['value']}" for r in false_records],
        "critical": critical,
        "pass": all(found) and not false_records and not critical,
    }


async def run_case(model: str, case: dict[str, Any], llm: Recorder) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="lazis-p6x-"))
    storage = open_storage(settings(root, model).storage, SecretBytes(secrets.token_bytes(32)), app_version="eval")
    engine = ConversationEngine(db=storage.db, get_llm=lambda: llm, settings=settings(root, model))  # type: ignore[arg-type,return-value]
    before = len(llm.extractions)
    try:
        await engine.ensure_started()
        session = await engine.start_new_session(model)
        seed(storage, case, session.id)
        handle = await engine.begin_turn(TurnRequest(session.id, f"eval-{case['id']}-{secrets.token_hex(4)}", case["message"], model))
        events = [e async for e in engine.events(handle)]
        reply = next((e["message"]["content"] for e in events if e["type"] == "done"), None)
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            counts = storage.db.run_sync(memory_repo.job_counts)
            if not counts.get("queued") and not counts.get("running") and engine.scheduler.background is None:
                break
            await asyncio.sleep(0.25)
        recs = records(storage)
        status = dict(engine.learner.status)
        jobs = storage.db.run_sync(memory_repo.job_counts)
    finally:
        await engine.close()
        storage.db.close()
        shutil.rmtree(root, ignore_errors=True)
    xs = llm.extractions[before:]
    return {
        "id": case["id"], "category": case["category"], "message": case["message"], "reply": reply,
        "records": recs, "learning": status, "jobs": jobs, "extraction": xs[-1] if xs else None,
        "extraction_requests": len(xs), "score": score(case, recs),
    }  # fmt: skip


async def run(model: str, only: set[str] | None) -> dict[str, Any]:
    gold = json.loads(GOLD.read_text())
    llm = Recorder(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200))
    results = []
    for case in gold["cases"]:
        if only and case["id"] not in only:
            continue
        r = await run_case(model, case, llm)
        s = r["score"]
        x = r["extraction"] or {}
        print(f"{case['id']:4} {'PASS' if s['pass'] else 'fail'} found {s['found']}/{s['expected']} "
              f"false {s['false_records']} crit {len(s['critical'])} "
              f"x={x.get('total_ms')}ms p={x.get('prompt_tokens')} o={x.get('output_tokens')} "
              f"{s['false_detail'][:3]} {s['critical'][:2]}", flush=True)  # fmt: skip
        results.append(r)
    await llm.inner.aclose()
    n = len(results)
    xs = [r["extraction"] for r in results if r["extraction"]]
    expected = sum(r["score"]["expected"] for r in results)
    summary = {
        "cases": n,
        "passed": sum(r["score"]["pass"] for r in results),
        "recall": round(sum(r["score"]["found"] for r in results) / max(expected, 1), 3),
        "false_records": sum(r["score"]["false_records"] for r in results),
        "critical": sum(len(r["score"]["critical"]) for r in results),
        "nothing_cases_with_records": sum(
            1 for r in results if r["category"] == "nothing" and r["score"]["false_records"]
        ),
        "invalid_json": sum(1 for r in results if r["learning"].get("code") == "llm_invalid_response"),
        "extraction_ms_median": sorted(x["total_ms"] for x in xs)[len(xs) // 2] if xs else None,
        "extraction_ms_max": max((x["total_ms"] for x in xs), default=None),
        "output_tokens_median": sorted(x["output_tokens"] or 0 for x in xs)[len(xs) // 2] if xs else None,
    }
    return {"model": model, "gold_version": gold["version"], "manifest": manifest(model), "summary": summary, "results": results}


def rescore(path: Path) -> None:
    """Recompute scores of a stored report with the current scoring rules (no model calls)."""
    report = json.loads(path.read_text())
    gold = {c["id"]: c for c in json.loads(GOLD.read_text())["cases"]}
    for r in report["results"]:
        r["score"] = score(gold[r["id"]], r["records"])
    results = report["results"]
    expected = sum(r["score"]["expected"] for r in results)
    report["summary"].update({
        "passed": sum(r["score"]["pass"] for r in results),
        "recall": round(sum(r["score"]["found"] for r in results) / max(expected, 1), 3),
        "false_records": sum(r["score"]["false_records"] for r in results),
        "critical": sum(len(r["score"]["critical"]) for r in results),
        "rescored": True,
    })  # fmt: skip
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(path.name, json.dumps(report["summary"], ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rescore", type=Path, nargs="*")
    ap.add_argument("--model")
    ap.add_argument("--only", default="")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    if args.rescore:
        for path in args.rescore:
            rescore(path)
        return
    assert args.model, "--model is required"
    only = {s.strip() for s in args.only.split(",") if s.strip()} or None
    report = asyncio.run(run(args.model, only))
    OUT.mkdir(parents=True, exist_ok=True)
    name = args.model.replace(":", "_").replace("/", "_")
    path = OUT / f"extraction_{name}{'_' + args.label if args.label else ''}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))
    print(path)


if __name__ == "__main__":
    main()
