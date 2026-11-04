"""The 40-message baseline conversation with a context checkpoint limit, on the private runtime.

    uv run --project core python evals/runners/p10p_supervise.py --detach --label long-cp8 --run 1 \
        --runner evals/runners/p10p_long_checkpoints.py --gaps 60-cp8 \
        --out evals/reports/phase10/perf/long-checkpoints

Same messages, order, model load, gap and engine settings as ``p10p_compaction_long.long_run``, so the
result compares with its baseline reports. Learning stays on. ``--gaps`` is ``<gap seconds>-cp<limit>``.
The limit reaches only this run's private server (``LLAMA_ARG_CTX_CHECKPOINTS``); the machine's Ollama
service, its settings and the real profile are not touched.

Added to the baseline's record, on stdout, so a stopped run keeps it: every model call with process
memory before and after, memory over time, the runtime's account of checkpoints, reuse and prompt
processing (numbers only; no other log line is kept), and memory by region at the end. After the last
turn the runtime stays idle for two minutes, which shows whether memory falls.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from pathlib import Path
from typing import Any

from common import manifest
from p3_context_eval import score
from p10p_compaction_long import (
    ENDPOINT,
    OUT,
    code_id,
    context_state,
    latency,
    machine_is_free,
    memory_summary,
    messages,
    sample_memory,
    settle,
    stored_equals_shown,
    turn,
)
from p10p_daily import Events
from p10p_memdiag_learning import (
    DiagRecorder,
    DiagServer,
    Runtime,
    emit,
    model_size,
    regions,
    watch_memory,
)
from p10s_compaction_turn import CAP, P, integrity

from lazis.conversation import repository as conv_repo
from lazis.memory import repository as memory_repo
from lazis.providers.llm.ollama import OllamaProvider

IDLE_AFTER_S = 120.0
LIMITS = {"cp8": 8}


def parse(name: str) -> tuple[float, int]:
    gap, _, limit = name.partition("-")
    if limit not in LIMITS:
        raise SystemExit(f"unknown checkpoint limit in {name}")
    return float(gap), LIMITS[limit]


async def run(model: str, name: str, cache_ram: int) -> dict[str, Any]:
    gap, limit = parse(name)
    sent, probes = messages()
    runtime = Runtime()
    server = DiagServer(cache_ram, runtime, limit)
    await server.start()
    llm = DiagRecorder(
        OllamaProvider(ENDPOINT, first_token_timeout=600, idle_timeout=120, max_duration=1200),
        server,
    )
    stop = asyncio.Event()
    mem: list[dict[str, Any]] = []
    sampler = asyncio.create_task(sample_memory(server, mem, stop))
    watcher = asyncio.create_task(watch_memory(server, stop))
    events = Events()
    logging.getLogger("lazis").addHandler(events)
    p = P(model, llm)
    n0 = len(CAP.events)
    try:
        await llm.inner.load(model, num_ctx=16384, keep_alive="10m")  # as the baseline
        emit({"model_size": {"moment": "after_load", **model_size()}})
        await p.start()
        assert p.engine is not None
        session = await p.engine.start_new_session(model)
        p.session_id = session.id
        turns = []
        for i, text in enumerate(sent):
            t = await turn(p, text)
            turns.append(t)
            emit({"i": i + 1, "first_s": round((t["first_delta_ms"] or 0) / 1000, 1),
                  "total_s": round(t["total_ms"] / 1000, 1), "tokens": t["prompt_tokens"],
                  "bg": t["background_at_send"], "stages": list(t["stages"]), "ctx": t["context"],
                  "memory": server.memory()})  # fmt: skip
            await asyncio.sleep(gap)
        settled = await settle(p)
        emit({"model_size": {"moment": "after_last_turn", **model_size()}})
        regions(server.pid(), "after_last_turn")
        at_end = server.memory()
        await asyncio.sleep(IDLE_AFTER_S)
        after_idle = server.memory()
        emit({"idle": {"seconds": IDLE_AFTER_S, "before": at_end, "after": after_idle}})
        regions(server.pid(), "after_idle")
        ev = [{k: v for k, v in e.items() if k != "t"} for e in CAP.events[n0:]]
        answers = {t["user"]: t["reply"] or "" for t in turns}
        scored = [
            {"q": q["q"], "answer": answers[q["q"]], **score(answers[q["q"]], q)} for q in probes
        ]

        def summaries(c: Any) -> list[dict[str, Any]]:
            return [{"version": x.version, "to_seq": x.to_seq, "status": x.status, "kept": x.kept_items,
                     "dropped": x.dropped_items, "rendered": x.rendered}
                    for x in conv_repo.list_summaries(c, p.session_id)]  # fmt: skip

        totals: dict[str, dict[str, float]] = {}
        for c in llm.calls:
            row = totals.setdefault(c["kind"], {"calls": 0, "complete": 0, "seconds": 0.0, "prompt_tokens": 0,
                                                "output_tokens": 0})  # fmt: skip
            row["calls"] += 1
            row["complete"] += c["ended"] == "complete"
            row["seconds"] = round(row["seconds"] + c["s"], 1)
            row["prompt_tokens"] += c.get("prompt_tokens") or 0
            row["output_tokens"] += c.get("output_tokens") or 0
        return {
            "gap_s": gap, "cache_ram": cache_ram, "checkpoint_limit_requested": limit, "latency": latency(turns),
            "turns": turns, "integrity": integrity(p, sent), "stored_equals_shown": stored_equals_shown(p, turns),
            "shown_equals_final": all(t["shown_equals_final"] for t in turns), "settle": settled,
            "history_uncovered_max": max(t["context"]["uncovered"] for t in turns),
            "trimmed": any(t["context"]["strategy"] == "window_only" for t in turns),
            "final_context": context_state(p), "compactions": ev,
            "completed": sum(e["event"] == "compaction.completed" for e in ev),
            "failed": sum(e["event"] == "compaction.failed" for e in ev),
            "probes": scored, "probes_passed": sum(x["pass"] for x in scored), "probes_total": len(scored),
            "summaries": p.q(summaries), "memories": p.memories(), "memory_jobs": p.q(memory_repo.job_counts),
            "memory_system": memory_summary(mem), "model_call_totals": totals, "model_calls": llm.calls,
            "calls_memory": llm.calls_memory, "events": events.rows, "memory_at_last_turn": at_end,
            "memory_after_idle": after_idle,
            "runtime": {"checkpoints_created": runtime.created, "checkpoints_erased": runtime.erased,
                        "checkpoints_erased_oldest": runtime.erased_old,
                        "checkpoints_erased_too_close": runtime.erased_too_close,
                        "checkpoints_restored": runtime.restored, "checkpoints_superseded": runtime.superseded,
                        "full_reprocess": runtime.full_reprocess, "prompt_eval_ms": round(runtime.prompt_eval_ms),
                        "prompt_eval_tokens": runtime.prompt_eval_tokens, "output_ms": round(runtime.output_ms),
                        "output_tokens": runtime.output_tokens, "checkpoint_limit": runtime.checkpoint_limit,
                        "checkpoint_mib": runtime.checkpoint_mib, "cache_limit_mib": runtime.cache_limit_mib,
                        **runtime.state()},
        }  # fmt: skip
    finally:
        stop.set()
        await sampler
        await watcher
        logging.getLogger("lazis").removeHandler(events)
        await p.stop()
        p.remove()
        await llm.inner.aclose()
        server.stop()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--cache-ram", type=int, default=2048)
    ap.add_argument("--gaps", required=True, help="<gap seconds>-cp8")
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args()
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    out = Path(os.environ.get("LAZIS_EVAL_OUT", OUT / "long-checkpoints"))
    out.mkdir(parents=True, exist_ok=True)
    machine_is_free()
    path = out / f"{a.label}_cache{a.cache_ram}_gap{a.gaps}_r{a.runs}.json"
    if path.exists():
        return
    meta = {"model": a.model, "label": a.label, "code": code_id(), "manifest": manifest(a.model)}
    report = asyncio.run(run(a.model, a.gaps, a.cache_ram))
    path.write_text(
        json.dumps({**meta, "started_run": a.runs, **report}, ensure_ascii=False, indent=1) + "\n"
    )
    emit({"path": path.name, "latency": report["latency"], "completed": report["completed"]})


if __name__ == "__main__":
    main()
