"""Phase 7.1: what the claim guard costs (real runtime, synthetic data).

    uv run --project core python evals/runners/p71_perf.py --model gemma4:12b-it-qat

* ``offline``: the guard alone on many replies and chunk sizes — time per chunk, the most
  text held back, peak memory (tracemalloc).
* ``live``: the same conversation (statements, questions, ordinary messages; memory on with
  1,000 synthetic records) with the guard on and off, alternating, ``--repeats`` times each.
  Per turn: TTFT (accepted → first model token), first shown (accepted → first text the user
  sees), total time, and the delay of every character from the model's stream to the user
  (arrival and display timestamped in the same process). Process RSS at the end.

Writes evals/reports/phase7_1/perf_<model>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import resource
import secrets
import shutil
import statistics
import tempfile
import time
import tracemalloc
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from common import manifest
from p6_perf import synthetic

from lazis.config.model import (
    AppSection,
    ConversationSection,
    LoggingSection,
    MemorySection,
    ModelsSection,
    Settings,
    StorageSection,
)
from lazis.conversation import ConversationEngine, TurnRequest
from lazis.memory import claims, service
from lazis.memory.service import Source
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import ChatRequest, StreamEvent, TextDelta
from lazis.security.secrets import SecretBytes
from lazis.storage import open_storage

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase7_1"
MESSAGES = [
    "Merhaba, bugün biraz plan yapmak istiyorum.",
    "Çocukluk arkadaşım Ahmet Yılmaz bu akşam bize gelecek.",
    "Ahmet'in kardeşi Mehmet, o da inşaat mühendisi.",
    "Hafta sonu için kısa bir gezi önerir misin?",
    "Kahveyi şekersiz içerim, akşamları da hiç içmem.",
    "Bunu unutma: perşembe günü saat ikide toplantım var.",
    "Bilgisayarımda 24 GB RAM var, yerel model için yeter mi?",
    "Eşim Aslı veteriner, oğlumuz Ege de altı yaşında.",
    "Ahmet'in kardeşi kimdi?",
    "Teşekkürler, şimdilik bu kadar.",
]
OFFLINE = [
    "Anlaşıldı efendim. Ahmet'in kardeşi Mehmet olduğunu not ettim; başka bir konu var mı?",
    "Anladım ve not aldım. Hafta sonu için Şirince güzel bir seçenek olabilir.",
    "Tamam efendim, bunu hafızama kaydettim. Bunu unutmayacağım.",
    "Merhaba efendim! " + "Bugün size planlarınızda yardımcı olabilirim, ne düşünüyorsunuz? " * 12,
    "Kaydettim efendim. Perşembe saat ikide toplantınız var.",
    "Bilgisayarınızdaki 24 GB RAM, 12B parametreli nicemlenmiş bir model için yeterlidir; "
    "bağlam uzunluğunu artırırsanız bellek kullanımı da artar. " * 4,
]


class Timed:
    """The production provider; timestamps the characters of the reply as they arrive."""

    def __init__(self, inner: OllamaProvider) -> None:
        self.inner = inner
        self.arrivals: list[float] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        reply = request.options.response_format is None and request.options.max_tokens > 1
        if reply:
            self.arrivals = []
        async for ev in self.inner.stream(request):
            if reply and isinstance(ev, TextDelta) and ev.kind == "content":
                self.arrivals += [time.monotonic()] * len(ev.text)
            yield ev


class _Off(claims.ClaimGuard):
    def feed(self, chunk: str) -> str:
        self.released += chunk
        return chunk

    def finish(self) -> str:
        return ""


def offline() -> dict[str, Any]:
    per_chunk: list[float] = []
    held_max = 0
    tracemalloc.start()
    for text in OFFLINE:
        for size in (1, 3, 4, 6, 12):
            for policy in (claims.Policy(claims.ClaimState.AUTO_LEARNING_PENDING),
                           claims.Policy(claims.ClaimState.SAVE_SUCCEEDED, memory_turn=True)):  # fmt: skip
                guard = claims.ClaimGuard(policy)
                for i in range(0, len(text), size):
                    t0 = time.perf_counter()
                    guard.feed(text[i : i + size])
                    per_chunk.append((time.perf_counter() - t0) * 1e6)
                    held_max = max(held_max, len(guard.pending))
                guard.finish()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    per_chunk.sort()
    return {
        "chunks": len(per_chunk),
        "us_per_chunk_median": round(statistics.median(per_chunk), 1),
        "us_per_chunk_p95": round(per_chunk[int(len(per_chunk) * 0.95)], 1),
        "us_per_chunk_max": round(per_chunk[-1], 1),
        "held_chars_max": held_max,
        "peak_kib_traced": round(peak / 1024, 1),
    }


async def conversation(model: str, guard: bool) -> list[dict[str, Any]]:
    root = Path(tempfile.mkdtemp(prefix="lazis-p71perf-"))
    settings = Settings(
        app=AppSection(environment="test"),
        storage=StorageSection(data_dir=root / "data"),
        logging=LoggingSection(directory=root / "logs"),
        models=ModelsSection(max_output_tokens=200),
        conversation=ConversationSection(idle_compaction_delay_s=3600.0),
        memory=MemorySection(auto_extract=True, context_budget_tokens=400),
    )
    storage = open_storage(settings.storage, SecretBytes(secrets.token_bytes(32)), app_version="eval")
    llm = Timed(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200))
    engine = ConversationEngine(db=storage.db, get_llm=lambda: llm, settings=settings)  # type: ignore[arg-type,return-value]
    original = claims.ClaimGuard
    if not guard:
        claims.ClaimGuard = _Off  # type: ignore[misc]
    rows: list[dict[str, Any]] = []
    try:
        cands = synthetic(1000, random.Random(7))
        for i in range(0, len(cands), 200):
            storage.db.run_sync(lambda c, b=cands[i : i + 200]: service.apply_candidates(
                c, b, source=Source("import"), explicit=True, actor="import", kind="import"))  # fmt: skip
        await engine.ensure_started()
        session = await engine.start_new_session(model)
        await engine.prepare(session.id, model)
        await asyncio.sleep(0.5)
        while engine.scheduler.background is not None:
            await asyncio.sleep(0.2)
        cid: str | None = session.id
        for i, text in enumerate(MESSAGES):
            handle = await engine.begin_turn(TurnRequest(cid, f"p71-{secrets.token_hex(6)}", text, model))
            shown: list[float] = []
            reply = None
            async for e in engine.events(handle):
                if e["type"] == "delta":
                    shown += [time.monotonic()] * len(e["text"])
                elif e["type"] == "done":
                    reply = e["message"]["content"]
            cid = handle.conversation.id
            last = dict(engine.last_turn or {})
            # Character delays: the k-th shown character against the k-th arrived one (a rewrite
            # changes lengths only inside a held sentence; compare the common prefix count).
            n = min(len(shown), len(llm.arrivals))
            delays = sorted((shown[k] - llm.arrivals[k]) * 1000 for k in range(n))
            rows.append({
                "turn": i + 1, "user": text, "reply": reply, "guard": guard,
                "ttft_ms": last.get("ttft_ms"), "first_shown_ms": last.get("first_shown_ms"),
                "total_ms": last.get("total_ms"), "runtime_ttft_ms": last.get("runtime_ttft_ms"),
                "output_tokens": last.get("output_tokens"), "decode_tps": last.get("decode_tps"),
                "claim_state": last.get("claim_state"), "rewrites": last.get("claims_rewritten"),
                "char_delay_ms_median": round(statistics.median(delays), 1) if delays else None,
                "char_delay_ms_p95": round(delays[int(len(delays) * 0.95)], 1) if delays else None,
                "char_delay_ms_max": round(delays[-1], 1) if delays else None,
            })  # fmt: skip
            t0 = time.monotonic()
            await asyncio.sleep(0.5)
            while engine.scheduler.background is not None or engine._pending:  # pyright: ignore[reportPrivateUsage]
                if time.monotonic() - t0 > 120:
                    break
                await asyncio.sleep(0.2)
    finally:
        claims.ClaimGuard = original  # type: ignore[misc]
        await engine.close()
        await llm.inner.aclose()
        storage.db.close()
        shutil.rmtree(root, ignore_errors=True)
    return rows


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    turns = [r for r in rows if r["turn"] > 1]

    def med(key: str) -> float | None:
        vals = [r[key] for r in turns if r[key] is not None]
        return round(statistics.median(vals), 1) if vals else None

    def top(key: str) -> float | None:
        vals = [r[key] for r in turns if r[key] is not None]
        return round(max(vals), 1) if vals else None

    gap = [r["first_shown_ms"] - r["ttft_ms"] for r in turns if r["first_shown_ms"] and r["ttft_ms"]]
    return {
        "turns": len(turns),
        "ttft_ms_median": med("ttft_ms"),
        "first_shown_ms_median": med("first_shown_ms"),
        "first_shown_minus_ttft_ms_median": round(statistics.median(gap), 1) if gap else None,
        "first_shown_minus_ttft_ms_max": round(max(gap), 1) if gap else None,
        "total_ms_median": med("total_ms"),
        "char_delay_ms_median": med("char_delay_ms_median"),
        "char_delay_ms_p95_max": top("char_delay_ms_p95"),
        "char_delay_ms_max": top("char_delay_ms_max"),
        "rewrites": sum(r["rewrites"] or 0 for r in rows),
    }


async def run(model: str, repeats: int) -> dict[str, Any]:
    live: dict[str, list[dict[str, Any]]] = {"on": [], "off": []}
    for _ in range(repeats):
        for name in ("off", "on"):
            rows = await conversation(model, name == "on")
            live[name] += rows
            print(name, json.dumps(summarise(rows)), flush=True)
    return {
        "model": model,
        "manifest": manifest(model),
        "offline": offline(),
        "live": {k: {"summary": summarise(v), "turns": v} for k, v in live.items()},
        "max_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--repeats", type=int, default=2)
    args = ap.parse_args()
    report = asyncio.run(run(args.model, args.repeats))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"perf_{re.sub(r'[:/]', '_', args.model)}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"offline": report["offline"], **{k: v["summary"] for k, v in report["live"].items()}}))
    print(path)


if __name__ == "__main__":
    main()
