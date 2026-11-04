"""The multi-cycle quality test at a context checkpoint limit, with raw summary output kept.

    uv run --project core python evals/runners/p10p_supervise.py --detach --label cycles-cp8 --run 1 \
        --runner evals/runners/p10p_cycles_checkpoints.py --gaps all \
        --out evals/reports/phase10/perf/cycles-cp8

This runs ``p10p_compaction_cycles.run`` itself, so dialogues, filler, seeds, versions, questions and
settings are the baseline's. Learning is off, as there. Only two names are replaced in that module:

- the private server, which gets ``LLAMA_ARG_CTX_CHECKPOINTS=8`` in its own environment and whose log
  is read for numbers (no other line is kept). The machine's service and settings are not touched.
- the seeded recorder, which also keeps each summary request's hash, raw output, output tokens and how
  it ended. Requests and events pass through unchanged, so keeping them does not change the test.

Synthetic data and throwaway profiles only. On stdout, so a stopped run keeps it: ``summary_call`` per
model call, before the ``i`` line of its compaction.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import signal
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import p10p_compaction_cycles as cycles
from common import manifest
from p10p_compaction_long import OUT, SeededRecorder, code_id, machine_is_free
from p10p_memdiag_learning import DiagServer, Runtime, emit

from lazis.conversation import compaction
from lazis.conversation.prompts import SECTIONS, SUMMARY_SCHEMA
from lazis.providers.llm.ports import ChatRequest, GenerationDone, StreamEvent, TextDelta

CHECKPOINTS = 8
RUNTIME = Runtime()
SERVERS: list[DiagServer] = []
CALLS: list[dict[str, Any]] = []


def make_server(cache_ram: int) -> DiagServer:
    server = DiagServer(cache_ram, RUNTIME, CHECKPOINTS)
    SERVERS.append(server)
    return server


def request_hash(request: ChatRequest) -> str:
    body = {"messages": [[m.role, m.content] for m in request.messages], "seed": request.options.seed,
            "max_tokens": request.options.max_tokens, "temperature": request.options.temperature}  # fmt: skip
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()[:16]


def read_output(text: str) -> dict[str, Any]:
    """How the raw output parses: whole, or salvaged after a cut, and the items in it by section."""
    whole = False
    try:
        whole = isinstance(json.loads(text.strip()), dict)
    except ValueError:
        pass
    parsed = compaction.parse_summary(text)
    items = {key: len(parsed.get(key) or []) for key, _ in SECTIONS} if parsed else {}
    return {"parse": "complete" if whole else "salvaged" if parsed else "failed", "items": items,
            "items_total": sum(items.values())}  # fmt: skip


class CaptureRecorder(SeededRecorder):
    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if request.options.response_format is not SUMMARY_SCHEMA:
            async for ev in super().stream(request):
                yield ev
            return
        t0 = time.monotonic()
        raw = ""
        metrics: dict[str, Any] = {}
        before = SERVERS[-1].memory() if SERVERS else None
        ended = "abandoned"
        try:
            async for ev in super().stream(request):
                if isinstance(ev, TextDelta) and ev.kind == "content":
                    raw += ev.text
                elif isinstance(ev, GenerationDone):
                    ended = "complete"
                    metrics = {"prompt_tokens": ev.metrics.prompt_tokens, "output_tokens": ev.metrics.output_tokens,
                               "done_reason": ev.metrics.done_reason}  # fmt: skip
                yield ev
        finally:
            row = {
                "at": time.strftime("%H:%M:%S"), "seed": self.seed, "request": request_hash(request),
                "max_tokens": request.options.max_tokens, "s": round(time.monotonic() - t0, 1), "ended": ended,
                **metrics, "at_limit": metrics.get("output_tokens") == request.options.max_tokens,
                **read_output(raw), "raw": raw, "memory_before": before,
                "memory_after": SERVERS[-1].memory() if SERVERS else None,
            }  # fmt: skip
            CALLS.append(row)
            emit({"summary_call": row})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--cache-ram", type=int, default=2048)
    ap.add_argument("--gaps", required=True, help="smoke, short or all")
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args()
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    out = Path(os.environ.get("LAZIS_EVAL_OUT", OUT / "cycles-cp8"))
    out.mkdir(parents=True, exist_ok=True)
    machine_is_free()
    path = out / f"{a.label}_cache{a.cache_ram}_gap{a.gaps}_r{a.runs}.json"
    if path.exists():
        return
    cycles.Server = make_server  # type: ignore[assignment,misc]
    cycles.SeededRecorder = CaptureRecorder  # type: ignore[misc]
    meta = {"model": a.model, "label": a.label, "code": code_id(), "manifest": manifest(a.model)}
    report = asyncio.run(cycles.run(a.model, a.gaps, a.cache_ram))
    runtime = {"checkpoint_limit": RUNTIME.checkpoint_limit, "checkpoints_created": RUNTIME.created,
               "checkpoints_erased": RUNTIME.erased, "checkpoints_erased_too_close": RUNTIME.erased_too_close,
               "checkpoints_erased_oldest": RUNTIME.erased_old, "checkpoints_restored": RUNTIME.restored,
               "checkpoints_superseded": RUNTIME.superseded, "full_reprocess": RUNTIME.full_reprocess,
               "prompt_eval_ms": round(RUNTIME.prompt_eval_ms), "prompt_eval_tokens": RUNTIME.prompt_eval_tokens,
               "output_ms": round(RUNTIME.output_ms), "output_tokens": RUNTIME.output_tokens, **RUNTIME.state()}  # fmt: skip
    path.write_text(
        json.dumps({**meta, "checkpoint_limit_requested": CHECKPOINTS, "runtime": runtime, "summary_calls": CALLS,
                    **report}, ensure_ascii=False, indent=1) + "\n"
    )  # fmt: skip
    emit({"path": path.name, "minutes": report["minutes"], "per_version": report["per_version"]})


if __name__ == "__main__":
    main()
