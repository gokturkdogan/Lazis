"""Phase 4: backend costs added by the desktop work, on the real runtime.

    uv run --project core python evals/runners/p4_desktop.py --model gemma4:12b-it-qat

Same method as p3_conversation.py (production engine, throwaway encrypted database with a
random in-memory key, synthetic Turkish history). Measures:

1. normal follow-up turns in a ~6K-token session (TTFT and total time, separately);
2. a long streamed reply (production output cap, 1024 tokens): total time and decode speed;
3. the diagnostics view's backend call (`engine.diagnostics()`, Ollama /api/ps + /api/tags)
   while idle and while a reply is streaming — it must not slow the reply down;
4. the status view's integrity check: first call (runs quick_check) vs cached.

Writes evals/reports/phase4/desktop_perf.json. The same-session numbers are directly
comparable with evals/reports/phase3/assistant_perf.json (Phase 3 harness, rerun on Phase 4
code as evals/reports/phase4/assistant_perf_rerun.json).
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
from p3_assistant import _activate
from p3_conversation import Bench

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase4"
LONG_PROMPT = (
    "Bana bir hafta sonu İstanbul gezisi için ayrıntılı bir plan yaz: iki gün, sabah-öğle-akşam, "
    "her durak için kısa açıklama ve ulaşım notu. En az 400 kelime olsun."
)


async def timed_ms(coro: Any) -> tuple[Any, float]:
    t0 = time.perf_counter()
    result = await coro
    return result, round((time.perf_counter() - t0) * 1000, 1)


async def run(model: str, reps: int) -> dict[str, Any]:
    rng = random.Random(20261018)
    root = Path(tempfile.mkdtemp(prefix="lazis-p4-desktop-"))
    report: dict[str, Any] = {"manifest": manifest(model), "scenarios": {}}
    scen = report["scenarios"]
    try:
        # The production output cap (1024) so the long reply really streams long.
        bench = Bench(model, root, compact_at=13000, max_output=1024)
        engine = await bench.open()
        session = await bench.seed(6000, rng)
        bench.storage.db.run_sync(lambda c: _activate(c, session))  # type: ignore[union-attr]
        await bench.prepare_and_wait(session)
        await bench.turn(None, "Merhaba, kısaca hazır mısın?")  # warm-up, discarded

        follow = [
            await bench.turn(None, q)
            for q in [
                "Bugün için kısa bir yapılacaklar listesi önerir misin?",
                "Bunlardan hangisi en önemli?",
                "Teşekkürler, bir de akşam için hafif bir yemek önerisi?",
                "Bunu iki cümlede özetler misin?",
                "Yarın sabah ilk iş ne yapmalıyım?",
            ][:reps]
        ]
        scen["normal_turns"] = {
            "rows": follow,
            "ttft_s": summarize([r["ttft_s"] for r in follow if r["ttft_s"] is not None]),
            "total_s": summarize([r["total_s"] for r in follow]),
        }

        long = await bench.turn(None, LONG_PROMPT)
        diag_after = engine.last_turn or {}
        scen["long_streaming"] = {
            **long,
            "decode_tps": diag_after.get("decode_tps"),
            "engine_total_ms": diag_after.get("total_ms"),
        }

        idle = []
        for _ in range(10):
            _, ms = await timed_ms(engine.diagnostics())
            idle.append(ms)
        scen["diagnostics_call_idle_ms"] = summarize(idle)

        # Diagnostics polled every 0.5 s (10x the panel's rate) during a long reply.
        polled: list[float] = []
        stop = asyncio.Event()

        async def poll() -> None:
            while not stop.is_set():
                _, ms = await timed_ms(engine.diagnostics())
                polled.append(ms)
                await asyncio.sleep(0.5)

        task = asyncio.create_task(poll())
        with_poll = await bench.turn(None, LONG_PROMPT.replace("İstanbul", "İzmir"))
        stop.set()
        await task
        tps_poll = (engine.last_turn or {}).get("decode_tps")
        scen["long_streaming_with_diagnostics_polling"] = {
            **with_poll,
            "decode_tps": tps_poll,
            "diagnostics_calls": len(polled),
            "diagnostics_call_ms": summarize(polled),
        }

        # Control: the same kind of turn right after, without polling. A long previous reply
        # adds ~1,000 new prompt tokens to process, independent of the diagnostics calls.
        control = await bench.turn(None, LONG_PROMPT.replace("İstanbul", "Bursa"))
        scen["long_streaming_control_after_long_reply"] = {
            **control,
            "decode_tps": (engine.last_turn or {}).get("decode_tps"),
            "context_prep_ms": (engine.last_turn or {}).get("context_prep_ms"),
        }

        assert bench.storage is not None
        bench.storage.db._quick_check_cache = None  # type: ignore[attr-defined]
        _, first_ms = await timed_ms(asyncio.to_thread(bench.storage.db.status))
        cached = []
        for _ in range(10):
            _, ms = await timed_ms(asyncio.to_thread(bench.storage.db.status))
            cached.append(ms)
        scen["status_integrity_check_ms"] = {"first_quick_check": first_ms, "cached": summarize(cached)}
        report["loaded_models_end"] = [m.name for m in await bench.llm.loaded_models()]
        await bench.close()
        await bench.llm.aclose()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--out", type=Path, default=OUT / "desktop_perf.json", help="report path (later phases rerun it)")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run(args.model, args.reps))
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report["scenarios"], ensure_ascii=False, indent=1)[:5000])


if __name__ == "__main__":
    main()
