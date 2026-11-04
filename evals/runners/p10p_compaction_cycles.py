"""Fact retention over several compactions (real Gemma, current code). No product change.

    uv run --project core python evals/runners/p10p_supervise.py --detach --label cycles --run 1 \
        --runner evals/runners/p10p_compaction_cycles.py --gaps all \
        --out evals/reports/phase10/perf/cycles --start-footprint-mb 40000 --start-swap-mb 40000

Design: docs/COMPACTION_MULTI_CYCLE_QUALITY_TEST.md. Each dialogue of tr_compaction_v1 is written to a
throwaway conversation and compacted through ``engine.compact_now``; a fixed block of unrelated
messages is added and it is compacted again, up to five summary versions, seeds 7 and 11. Then the
dataset's questions are asked in that conversation. Learning is off here: the history is written
directly, so this reads the summary alone. The daily scenarios read summary, memory and prompt together.

One line per compaction and per question on stdout. A compaction that does nothing fails its
conversation visibly; it is never skipped. Every rendered summary is in the report, to read by hand.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common import manifest
from p3_context_eval import DATA, score
from p10p_compaction_long import (
    ENDPOINT,
    OUT,
    QualityProfile,
    SeededRecorder,
    Server,
    code_id,
    machine_is_free,
    memory_summary,
    sample_memory,
    turn,
)
from p10p_daily import hedged
from p10s_compaction_turn import SEED_A, SEED_Q

from lazis.config.model import AppSection, ConversationSection, LoggingSection, MemorySection, Settings, StorageSection
from lazis.conversation import repository as conv_repo
from lazis.conversation.compaction import normalize
from lazis.ids import utc_now_iso
from lazis.providers.llm.ollama import OllamaProvider

VERSIONS = 5
FILLER_ROUNDS = 8
UNCERTAIN = {"D1": ["Mehmet"]}  # said as a possibility; a summary must keep it so
OLD_VALUES = {"D1": ["salı"], "D2": ["React"], "D4": ["9:00"], "D5": ["Antalya"]}  # replaced in the dialogue


@dataclass
class CycleProfile(QualityProfile):
    def settings(self) -> Settings:
        return Settings(
            app=AppSection(environment="test"),
            storage=StorageSection(data_dir=self.root / "data"),
            logging=LoggingSection(directory=self.root / "logs"),
            conversation=ConversationSection(idle_compaction_delay_s=3600.0, prewarm=False, keep_recent_tokens=self.keep),
            memory=MemorySection(auto_extract=False),
        )  # fmt: skip


def read_version(summary: Any, d: dict[str, Any], seen: set[str]) -> dict[str, Any]:
    text = normalize(summary.rendered)
    expected = [w for w, seq in d["summary_expect"] if seq <= summary.to_seq]
    missing = [w for w in expected if normalize(w) not in text]
    present = {w for w in expected if normalize(w) in text}
    lost = sorted(seen - present)
    seen |= present
    lines = summary.rendered.splitlines()
    uncertain = {}
    for name in UNCERTAIN.get(d["id"], []):
        about = [x for x in lines if name in x]
        uncertain[name] = {"mentioned": bool(about), "hedged": any(hedged(x) for x in about)}
    return {"version": summary.version, "to_seq": summary.to_seq, "expected": len(expected), "missing": missing,
            "lost_since_earlier": lost, "silent_loss": bool(lost) and not summary.dropped_items,
            "kept": summary.kept_items, "dropped": summary.dropped_items, "uncertain": uncertain,
            "old_values_present": [w for w in OLD_VALUES.get(d["id"], []) if normalize(w) in text],
            "rendered": summary.rendered}  # fmt: skip


async def one(model: str, d: dict[str, Any], seed: int, versions: int, probes: int, counter: list[int]) -> dict[str, Any]:
    llm = SeededRecorder(OllamaProvider(ENDPOINT, first_token_timeout=600, idle_timeout=120, max_duration=1200), seed)
    p = CycleProfile(model, llm, keep=2048)
    rows: list[dict[str, Any]] = []
    try:
        await p.start()
        assert p.engine is not None
        session = await p.engine.start_new_session(model)
        cid = session.id
        p.session_id = cid

        def write(history: list[tuple[str, str]]) -> None:
            def tx(c: Any) -> None:
                with conv_repo.transaction(c):
                    for role, text in history:
                        conv_repo.insert_message(c, conversation_id=cid, role=role, content=text, status="complete",
                                                 now=utc_now_iso(), model=None if role == "user" else model)  # fmt: skip

            p.q(tx)

        filler = [x for i in range(FILLER_ROUNDS) for x in (("user", SEED_Q[i % len(SEED_Q)]), ("assistant", SEED_A * 3))]
        write([(r, c) for r, c in d["messages"]] + filler)
        seen: set[str] = set()
        failed = None
        for k in range(versions):
            t0 = time.monotonic()
            done = await p.engine.compact_now(cid)
            s = round(time.monotonic() - t0, 1)
            active = next((x for x in p.q(lambda c: conv_repo.list_summaries(c, cid)) if x.status == "active"), None)
            if not done or active is None:
                failed = f"compaction {k + 1} did nothing"
                print(json.dumps({"failed": failed, "dialogue": d["id"], "seed": seed}), flush=True)
                break
            row = {"cycle": k + 1, "s": s, **read_version(active, d, seen)}
            rows.append(row)
            counter[0] += 1
            print(json.dumps({"i": counter[0], "dialogue": d["id"], "seed": seed, "cycle": k + 1, "s": s,
                              "missing": row["missing"], "lost": row["lost_since_earlier"], "silent": row["silent_loss"],
                              "uncertain": row["uncertain"], "kept": row["kept"], "dropped": row["dropped"]},
                             ensure_ascii=False), flush=True)  # fmt: skip
            if k + 1 < versions:
                write(filler)
        answers = []
        if failed is None:
            for q in d["probes"][:probes]:
                t = await turn(p, q["q"])
                answers.append({"q": q["q"], "answer": t["reply"] or "", "first_s": round((t["first_delta_ms"] or 0) / 1000, 1),
                                **score(t["reply"] or "", q)})  # fmt: skip
                print(json.dumps({"q": q["q"], "pass": answers[-1]["pass"]}, ensure_ascii=False), flush=True)
        return {"dialogue": d["id"], "seed": seed, "failed": failed, "cycles": rows, "answers": answers}
    finally:
        await p.stop()
        p.remove()
        await llm.inner.aclose()


async def run(model: str, name: str, cache_ram: int) -> dict[str, Any]:
    dialogues = json.loads(DATA.read_text())["dialogues"]
    if name not in ("smoke", "short", "all"):
        raise SystemExit(f"unknown set {name}")
    by_id = {d["id"]: d for d in dialogues}
    plans = {
        "smoke": ([(by_id["D1"], 7)], 2, 1),
        # Up to the third version, where the baseline first loses facts in these conversations.
        "short": ([(by_id[i], s) for i, s in (("D1", 7), ("D1", 11), ("D3", 11), ("D5", 7))], 3, 99),
        "all": ([(d, s) for s in (7, 11) for d in dialogues], VERSIONS, 99),
    }
    plan = plans[name]
    server = Server(cache_ram)
    await server.start()
    stop = asyncio.Event()
    mem: list[dict[str, Any]] = []
    sampler = asyncio.create_task(sample_memory(server, mem, stop))
    started = time.time()
    counter = [0]
    rows = []
    try:
        for d, seed in plan[0]:
            rows.append(await one(model, d, seed, plan[1], plan[2], counter))
    finally:
        stop.set()
        await sampler
        server.stop()
    last = [r["cycles"][-1] for r in rows if r["cycles"]]
    answers = [a for r in rows for a in r["answers"]]
    per_version: dict[int, dict[str, int]] = {}
    for r in rows:
        for c in r["cycles"]:
            v = per_version.setdefault(c["cycle"], {"expected": 0, "missing": 0, "silent_losses": 0})
            v["expected"] += c["expected"]
            v["missing"] += len(c["missing"])
            v["silent_losses"] += c["silent_loss"]
    return {
        "set": name, "minutes": round((time.time() - started) / 60, 1), "versions": plan[1],
        "per_version": per_version,
        "final_facts": sum(c["expected"] for c in last), "final_missing": sum(len(c["missing"]) for c in last),
        "failed_conversations": [r["dialogue"] for r in rows if r["failed"]],
        "answers_passed": sum(a["pass"] for a in answers), "answers_total": len(answers),
        "rows": rows, "memory_system": memory_summary(mem),
    }  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--cache-ram", type=int, default=2048)
    ap.add_argument("--gaps", required=True, help="smoke, short or all")
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args()
    out = Path(os.environ.get("LAZIS_EVAL_OUT", OUT / "cycles"))
    out.mkdir(parents=True, exist_ok=True)
    machine_is_free()
    path = out / f"{a.label}_cache{a.cache_ram}_gap{a.gaps}_r{a.runs}.json"
    if path.exists():
        return
    meta = {"model": a.model, "label": a.label, "code": code_id(), "manifest": manifest(a.model)}
    report = asyncio.run(run(a.model, a.gaps, a.cache_ram))
    path.write_text(json.dumps({**meta, **report}, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"path": path.name, "minutes": report["minutes"], "per_version": report["per_version"]}), flush=True)


if __name__ == "__main__":
    main()
