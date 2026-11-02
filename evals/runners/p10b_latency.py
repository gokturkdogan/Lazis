"""Phase 10B closing: where do the 137–150 s first-token pauses come from? (real Gemma)

    uv run --project core python evals/runners/p10b_latency.py . > evals/reports/phase10/latency_<code>.jsonl

Same 20 questions in four conditions, throwaway encrypted profiles, the production engine:
  A on_eval      layer 2 on, "Daha ayrıntılı anlat", idle compaction delay 3600 s (the eval's)
  B off_eval     layer 2 off, same messages, delay 3600 s
  C offlong_eval layer 2 off, every question + " Ayrıntılı anlat.", delay 3600 s
  D on_prod      layer 2 on, "Daha ayrıntılı anlat", the production default delay (5 s)
Per turn: when each engine stage began (waiting, compacting, processing_context, generating),
the diagnostics (context prep, runtime TTFT, memory, first shown), prompt tokens, and the
compaction events in the profile's log; then the wait for background work to settle (as the
eval runners do).
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, sys.argv[1] + "/evals/runners")
import p10b_adaptation as R  # noqa: E402
from p6_sessions import Profile, Recorder  # noqa: E402

from lazis.config.model import AppSection, ConversationSection, LoggingSection, Settings, StorageSection  # noqa: E402
from lazis.conversation import TurnRequest  # noqa: E402
from lazis.memory import repository as memory_repo  # noqa: E402
from lazis.personality import Layers  # noqa: E402
from lazis.providers.llm.ollama import OllamaProvider  # noqa: E402

MODEL = "gemma4:12b-it-qat"
QS = R.QUESTIONS


@dataclass
class P(Profile):
    delay: float = 3600.0

    def settings(self) -> Settings:
        return Settings(
            app=AppSection(environment="test"),
            storage=StorageSection(data_dir=self.root / "data"),
            logging=LoggingSection(directory=self.root / "logs"),
            conversation=ConversationSection(idle_compaction_delay_s=self.delay),
        )


class Capture(logging.Handler):
    """The engine's structured events (compaction, pre-warm, learning), with their time."""

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.events: list[dict[str, Any]] = []
        self.t0 = time.monotonic()

    def emit(self, record: logging.LogRecord) -> None:
        name = record.getMessage()
        if any(k in name for k in ("compaction", "prewarm", "rewarm", "learning", "turn.started")):
            self.events.append({"t_ms": round((time.monotonic() - self.t0) * 1000), "event": name,
                                **(getattr(record, "lazis_fields", None) or {})})


CAP = Capture()
logging.getLogger("lazis").addHandler(CAP)
logging.getLogger("lazis").setLevel(logging.INFO)


def log_events(p: P, seen: int) -> tuple[list[dict[str, Any]], int]:
    return CAP.events[seen:], len(CAP.events)


async def turn(p: P, text: str) -> dict[str, Any]:
    assert p.engine is not None
    t0 = time.monotonic()
    h = await p.engine.begin_turn(TurnRequest(p.session_id, f"perf-{secrets.token_hex(6)}", text, MODEL))
    stages: dict[str, float] = {}
    first = None
    reply = ""
    async for e in p.engine.events(h):
        now = round((time.monotonic() - t0) * 1000)
        if e["type"] == "status":
            stages.setdefault(e["stage"], now)
        elif e["type"] == "delta" and first is None:
            first = now
        elif e["type"] == "done":
            reply = e["message"]["content"]
    p.session_id = h.conversation.id
    last = dict(p.engine.last_turn or {})
    s0 = time.monotonic()
    while time.monotonic() - s0 < 300:
        counts = p.q(memory_repo.job_counts)
        if not counts.get("queued") and not counts.get("running") and p.engine.scheduler.background is None:
            break
        await asyncio.sleep(0.25)
    settle = round((time.monotonic() - s0) * 1000)
    keys = ("ttft_ms", "context_prep_ms", "runtime_ttft_ms", "first_shown_ms", "total_ms", "memory_ms",
            "memory_request_ms", "prompt_tokens", "output_tokens", "style_reminded", "dois_unverified")
    return {"stages": stages, "first_delta_ms": first, "settle_ms": settle,
            "words": len(reply.split()), **{k: last.get(k) for k in keys}}


async def condition(name: str, llm: Recorder, *, on: bool, long: bool, delay: float) -> list[dict[str, Any]]:
    p = P(MODEL, llm, delay=delay)
    rows: list[dict[str, Any]] = []
    seen = 0
    try:
        await p.start()
        if not on:
            p.engine.layers = Layers(preferences=False)  # type: ignore[union-attr]
        r = await turn(p, "Daha ayrıntılı anlat.")
        ev, seen = log_events(p, seen)
        rows.append({"cond": name, "i": 0, "msg": "instruction", **r, "log": ev})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
        for i, q in enumerate(QS, 1):
            r = await turn(p, q + (" Ayrıntılı anlat." if long else ""))
            ev, seen = log_events(p, seen)
            rows.append({"cond": name, "i": i, "msg": q[:40], **r, "log": ev})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    finally:
        await p.stop()
        p.remove()
    return rows


async def main() -> None:
    llm = Recorder(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200))
    only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
    plan = [("A_on_eval", True, False, 3600.0), ("B_off_eval", False, False, 3600.0),
            ("C_offlong_eval", False, True, 3600.0), ("D_on_prod", True, False, 5.0)]
    for name, on, long, delay in plan:
        if only and name not in only:
            continue
        await condition(name, llm, on=on, long=long, delay=delay)
    await llm.inner.aclose()


asyncio.run(main())
