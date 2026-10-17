"""Phase 3 addendum: performance of the single-assistant model (ADR-0011) on the real runtime.

    uv run --project core python evals/runners/p3_assistant.py --model gemma4:12b-it-qat

Same method as p3_conversation.py (production engine, throwaway encrypted database with a
random in-memory key, synthetic Turkish history carrying runtime token counts, Ollama with the
current LaunchAgent settings). Reports TTFT and total response time separately, and the
pre-warm duration on its own. Scenarios:

1. opening LAZIS with an existing ~6K-token active session after the runtime restarted
   (model unloaded): send at once / 10 s after opening / after the pre-warm finished;
2. the 2nd and 3rd message in the same session;
3. closing and reopening the app while the runtime keeps running;
4. a long-time user: 20,000 older messages in closed sessions plus the active session —
   timeline paging latency (API layer: engine + encrypted database) and the first turn;
5. a technical session change (`start_new_session`) and its first message;
6. whether pre-warming really completed (the turn must report a warm cache).

Writes evals/reports/phase3/assistant_perf.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from common import manifest, summarize
from p3_conversation import OUT, Bench, runner_footprint_gb

from lazis.conversation import repository
from lazis.ids import utc_now_iso

HISTORY_TOKENS = 6000
OLD_MESSAGES = 20_000


def seed_closed_history(bench: Bench, count: int) -> None:
    """``count`` messages in 200 closed sessions (older than the active session)."""
    assert bench.storage is not None
    now = utc_now_iso()

    def write(conn: repository.Connection) -> None:
        with repository.transaction(conn):
            active = repository.get_active_session(conn)
            per = count // 200
            for s in range(200):
                session = repository.insert_conversation(
                    conn, title=f"eski {s}", model=bench.model, now=now, status="archived"
                )
                for i in range(per):
                    repository.insert_message(
                        conn,
                        conversation_id=session.id,
                        role="user" if i % 2 == 0 else "assistant",
                        content=f"Eski mesaj {s}-{i}: bugün kısa bir not daha ekliyorum.",
                        status="complete",
                        now=now,
                    )
            if active is not None:
                # Keep the active session's messages newest in the timeline, as in real use.
                conn.execute(
                    "UPDATE messages SET timeline_seq = timeline_seq + ? WHERE conversation_id = ?",
                    (count * 10, active.id),
                )

    bench.storage.db.run_sync(write)


async def timed(coro: Any) -> tuple[Any, float]:
    t0 = time.perf_counter()
    result = await coro
    return result, round((time.perf_counter() - t0) * 1000, 1)


async def run(model: str) -> dict[str, Any]:
    rng = random.Random(20261018)
    root = Path(tempfile.mkdtemp(prefix="lazis-p3-assistant-"))
    report: dict[str, Any] = {"manifest": manifest(model), "scenarios": {}}
    scen = report["scenarios"]
    memory: list[dict[str, Any]] = []
    report["memory"] = memory
    try:
        bench = Bench(model, root, compact_at=13000)
        engine = await bench.open()
        session = await bench.seed(HISTORY_TOKENS, rng)
        bench.storage.db.run_sync(lambda c: _activate(c, session))  # type: ignore[union-attr]

        async def reopen(*, unload: bool) -> None:
            nonlocal engine
            await bench.close()
            if unload:
                await bench.llm.unload(model)
                await asyncio.sleep(2)
            engine = await bench.open()

        # 1. Opening LAZIS after the runtime restarted (model unloaded, caches empty).
        rows: dict[str, Any] = {}
        await reopen(unload=True)
        rows["send_at_once"] = await bench.turn(None, "Günaydın, bugün neler yapalım?")
        await reopen(unload=True)
        t0 = time.perf_counter()
        await engine.prepare(session, model)  # what the UI does when LAZIS opens
        await asyncio.sleep(10.0)
        rows["send_after_10s"] = {**await bench.turn(None, "Bir de akşam için öneri?"), "send_after_s": 10.0}
        await reopen(unload=True)
        t0 = time.perf_counter()
        state = await engine.prepare(session, model)
        job = engine.scheduler.background
        if job is not None and job.task is not None:
            await job.task
        prewarm_s = round(time.perf_counter() - t0, 3)
        rows["send_after_prewarm"] = {
            **await bench.turn(None, "Peki hafta sonu?"),
            "prewarm_s": prewarm_s,
            "prepare_state": state.get("state"),
        }
        scen["open_after_runtime_restart"] = rows
        memory.append({"at": "after opening", "runner_gb": runner_footprint_gb()})

        # 2. Second and third message in the same session.
        scen["same_session_followups"] = [
            await bench.turn(None, "Bunu kısaca özetler misin?"),
            await bench.turn(None, "Teşekkürler, bir de kısa bir hatırlatma notu yazar mısın?"),
        ]

        # 3. Close and reopen the app; the runtime keeps running.
        await reopen(unload=False)
        pre_state = await engine.prepare(session, model)
        job = engine.scheduler.background
        if job is not None and job.task is not None:
            await job.task
        scen["app_reopen_runtime_running"] = {
            **await bench.turn(None, "Kaldığımız yerden devam edelim."),
            "prepare_state": pre_state.get("state"),
        }

        # 4. Long-time user: 20,000 older messages in closed sessions.
        seed_closed_history(bench, OLD_MESSAGES)
        state_info, state_ms = await timed(engine.assistant_state())
        first_page, first_ms = await timed(engine.timeline(before_timeline_seq=None, limit=50))
        deep: list[float] = []
        before: int | None = first_page[0][0].timeline_seq
        for _ in range(20):  # scroll back 20 pages
            (page, _more), ms = await timed(engine.timeline(before_timeline_seq=before, limit=50))
            deep.append(ms)
            before = page[0].timeline_seq
        far, far_ms = await timed(engine.timeline(before_timeline_seq=5_000, limit=50))
        scen["long_history"] = {
            "timeline_messages": state_info["timeline_messages"],
            "assistant_state_ms": state_ms,
            "first_page_ms": first_ms,
            "older_pages_ms": summarize(deep),
            "page_near_message_5000_ms": far_ms,
            "page_size": 50,
            "first_turn": await bench.turn(None, "Eski konuşmalar çok uzun, ama şimdi yeni bir soru."),
        }
        memory.append({"at": "after long history", "runner_gb": runner_footprint_gb()})

        # 5. Technical session change and its first message.
        new_session = await engine.start_new_session(model)
        change_cold = await bench.turn(None, "Yeni bir konuya geçelim.")
        assert change_cold["conversation_id"] == new_session.id
        second_session = await engine.start_new_session(model)
        pre = await bench.prepare_and_wait(second_session.id)
        change_prewarmed = {**await bench.turn(None, "Başka bir konu daha."), **pre}
        scen["session_change"] = {"no_prewarm": change_cold, "prewarmed": change_prewarmed}

        # 6. Did the pre-warm complete? (the turn must see a warm cache)
        checks = [
            rows["send_after_prewarm"]["cache_expected"] == "warm",
            scen["app_reopen_runtime_running"]["cache_expected"] == "warm",
            change_prewarmed["cache_expected"] == "warm",
        ]
        scen["prewarm_completed"] = {"turns_reporting_warm_after_prewarm": f"{sum(checks)}/{len(checks)}"}
        memory.append({"at": "end", "runner_gb": runner_footprint_gb()})
        report["resident_gb_end"] = await bench.loaded_size_gb()
        report["loaded_models_end"] = [m.name for m in await bench.llm.loaded_models()]
        await bench.close()
        await bench.llm.aclose()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return report


def _activate(conn: repository.Connection, session_id: str) -> None:
    with repository.transaction(conn):
        repository.activate_session(conn, session_id)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", type=Path, default=OUT / "assistant_perf.json", help="report path (Phase 4 reruns write elsewhere)")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run(args.model))
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report["scenarios"], ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()
