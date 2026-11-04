"""Does a summary take in what arrives or changes after its first version? (real Gemma, current code)

    uv run --project core python evals/runners/p10p_supervise.py --detach --label late --run 1 \
        --runner evals/runners/p10p_late_facts.py --gaps late --out evals/reports/phase10/perf/late-facts

Data: evals/datasets/tr_late_facts_v1.json. Each phase's messages and a filler block are written, then
compacted. Then the questions are asked. It measures the system as it is: no product change, learning
off, so this reads the summary alone. The private server has context checkpoints limited to 8. Every
version and raw output is kept, to read by hand; a word found is not a fact kept.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import time
from pathlib import Path
from typing import Any

from common import manifest
from p3_context_eval import DATA, score
from p10p_compaction_cycles import FILLER_ROUNDS, CycleProfile
from p10p_compaction_long import (
    ENDPOINT,
    OUT,
    code_id,
    machine_is_free,
    memory_summary,
    sample_memory,
    turn,
)
from p10p_cycles_checkpoints import CALLS, CaptureRecorder, make_server
from p10p_memdiag_learning import emit
from p10s_compaction_turn import SEED_A, SEED_Q

from lazis.conversation import repository as conv_repo
from lazis.ids import utc_now_iso
from lazis.providers.llm.ollama import OllamaProvider

SET = DATA.parent / "tr_late_facts_v1.json"
SEEDS = (7, 11)
YEAR = re.compile(r"\b(19|20)\d\d\b")


async def one(model: str, data: dict[str, Any], seed: int, counter: list[int]) -> dict[str, Any]:
    llm = CaptureRecorder(
        OllamaProvider(ENDPOINT, first_token_timeout=600, idle_timeout=120, max_duration=1200), seed
    )
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

        filler = [
            x
            for i in range(FILLER_ROUNDS)
            for x in (("user", SEED_Q[i % len(SEED_Q)]), ("assistant", SEED_A * 3))
        ]
        said = ""
        for k, phase in enumerate(data["phases"], start=1):
            said += " ".join(c for _, c in phase["messages"])
            write([(r, c) for r, c in phase["messages"]] + filler)
            t0 = time.monotonic()
            done = await p.engine.compact_now(cid)
            s = round(time.monotonic() - t0, 1)
            active = next(
                (
                    x
                    for x in p.q(lambda c: conv_repo.list_summaries(c, cid))
                    if x.status == "active"
                ),
                None,
            )
            assert done and active is not None, f"compaction after {phase['name']} did nothing"
            audit = (await p.engine.summary_audit(cid))[-1]
            counter[0] += 1
            row = {"phase": phase["name"], "stage": k, "version": active.version, "to_seq": active.to_seq, "s": s,
                   "kept": active.kept_items, "dropped": active.dropped_items, "rendered": active.rendered,
                   "invented_years": sorted(set(m.group(0) for m in YEAR.finditer(active.rendered))
                                            - set(m.group(0) for m in YEAR.finditer(said))),
                   "possibly_lost": audit["possibly_lost"], "became_certain": audit["became_certain"]}  # fmt: skip
            rows.append(row)
            emit({"i": counter[0], "seed": seed, "phase": phase["name"], "version": active.version, "s": s,
                  "kept": active.kept_items, "dropped": active.dropped_items, "years": row["invented_years"]})  # fmt: skip
        answers = []
        for q in data["probes"]:
            t = await turn(p, q["q"])
            answers.append({"q": q["q"], "answer": t["reply"] or "", "first_s": round((t["first_delta_ms"] or 0) / 1000, 1),
                            **score(t["reply"] or "", q)})  # fmt: skip
            emit({"q": q["q"], "pass": answers[-1]["pass"]})
        return {"seed": seed, "versions": rows, "answers": answers}
    finally:
        await p.stop()
        p.remove()
        await llm.inner.aclose()


async def run(model: str, cache_ram: int) -> dict[str, Any]:
    data = json.loads(SET.read_text("utf-8"))
    server = make_server(cache_ram)
    await server.start()
    stop = asyncio.Event()
    mem: list[dict[str, Any]] = []
    sampler = asyncio.create_task(sample_memory(server, mem, stop))
    started = time.time()
    counter = [0]
    rows = []
    try:
        for seed in SEEDS:
            rows.append(await one(model, data, seed, counter))
    finally:
        stop.set()
        await sampler
        server.stop()
    return {"minutes": round((time.time() - started) / 60, 1), "rows": rows, "summary_calls": CALLS,
            "memory_system": memory_summary(mem)}  # fmt: skip


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--cache-ram", type=int, default=2048)
    ap.add_argument("--gaps", required=True, help="late")
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args()
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    out = Path(os.environ.get("LAZIS_EVAL_OUT", OUT / "late-facts"))
    out.mkdir(parents=True, exist_ok=True)
    machine_is_free()
    path = out / f"{a.label}_cache{a.cache_ram}_gap{a.gaps}_r{a.runs}.json"
    if path.exists():
        return
    meta = {"model": a.model, "label": a.label, "code": code_id(), "manifest": manifest(a.model)}
    report = asyncio.run(run(a.model, a.cache_ram))
    path.write_text(json.dumps({**meta, **report}, ensure_ascii=False, indent=1) + "\n")
    emit({"path": path.name, "minutes": report["minutes"]})


if __name__ == "__main__":
    main()
