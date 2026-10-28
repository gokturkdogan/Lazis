"""Phase 9 performance on this machine: chat while learning, with conversation loads of 20,
100 and 500 facts (synthetic data only).

    uv run --project core python evals/runners/p9_perf.py --model gemma4:12b-it-qat
    uv run --project core python evals/runners/p9_perf.py --sizes 20 --label quick

For each size, a throwaway encrypted profile; messages carrying five facts each are sent;
after every message the user pauses long enough for background learning to start, then sends
a short chat turn (which preempts the learning) — its first-token time is "chat while
learning". Also measured: chat when nothing runs, how long a message waits until it is learned
from (queue latency), model calls (chat, extraction, list re-reads), what was written, the
backend's peak RSS and the model runner's footprint. Conversation settings are the app's own
(compaction after 5 s idle): the session evaluations' profile postpones compaction for an hour,
and learning waits behind a compaction a long conversation needs. Writes
evals/reports/phase9/perf_<model>.json after every size.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import resource
import secrets
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from common import footprint_mb, manifest, runner_pids
from p6_sessions import Profile, Recorder

from lazis.config.model import ConversationSection, Settings
from lazis.conversation import TurnRequest
from lazis.conversation.prompts import SUMMARY_SCHEMA
from lazis.memory import repository as repo
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import ChatRequest

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase9"
NAMES = ["Aras", "Bora", "Ceren", "Defne", "Emre", "Funda", "Gökhan", "Hale", "Irmak", "Kaan",
         "Lale", "Mert", "Nil", "Onur", "Pelin", "Rüzgar", "Selin", "Tuna", "Umut", "Vera"]  # fmt: skip
SURNAMES = ["Akın", "Bulut", "Çelik", "Demir", "Ekinci", "Fidan"]
RELS = ["Kuzenim", "Arkadaşım", "Komşum", "İş arkadaşım"]
JOBS = ["mimar", "öğretmen", "hemşire", "avukat", "aşçı", "pilot", "eczacı", "veteriner"]
CITIES = ["Bursa", "Eskişehir", "Trabzon", "Konya", "Muğla", "Edirne", "Rize", "Sinop"]
HOBBIES = ["satranç", "yüzme", "seramik", "tırmanış", "dalış", "okçuluk", "kayak", "yelken"]
SMALL_TALK = ["Bugün ne yemek yapsam?", "Bana kısa bir espri yapar mısın?",
              "Akşam yürüyüşü için bir öneri?", "Hafta sonu için bir fikir?"]  # fmt: skip


def message(i: int) -> str:
    """Five facts: the relationship, a job, a city, two interests."""
    name = f"{NAMES[i % len(NAMES)]} {SURNAMES[(i // len(NAMES)) % len(SURNAMES)]}"
    return (f"{RELS[i % len(RELS)]} {name} {JOBS[i % len(JOBS)]}, "
            f"{CITIES[i % len(CITIES)]}'da yaşıyor; {HOBBIES[i % len(HOBBIES)]} ve "
            f"{HOBBIES[(i + 3) % len(HOBBIES)]} ile ilgileniyor.")  # fmt: skip


class PerfProfile(Profile):
    def settings(self) -> Settings:
        return super().settings().model_copy(update={"conversation": ConversationSection()})


class Counter(Recorder):
    def __init__(self, inner: OllamaProvider) -> None:
        super().__init__(inner)
        self.calls = {"chat": 0, "extraction": 0, "list_reread": 0, "compaction": 0, "other": 0}

    async def stream(self, request: ChatRequest) -> Any:
        fmt = request.options.response_format
        content = request.messages[-1].content if request.messages else ""
        if fmt is None and request.options.max_tokens > 1:
            self.calls["chat"] += 1
        elif isinstance(fmt, dict) and "items" in fmt.get("properties", {}):
            self.calls["list_reread" if "EKSİK LİSTE" in content else "extraction"] += 1
        elif fmt is SUMMARY_SCHEMA:
            self.calls["compaction"] += 1
        else:
            self.calls["other"] += 1
        async for ev in self.inner.stream(request):
            yield ev


async def turn(p: Profile, text: str) -> float | None:
    assert p.engine is not None
    t0 = time.monotonic()
    first = None
    h = await p.engine.begin_turn(TurnRequest(p.session_id, f"perf-{secrets.token_hex(6)}", text, p.model))
    async for e in p.engine.events(h):
        if e["type"] == "delta" and first is None:
            first = time.monotonic() - t0
    return None if first is None else round(first, 2)


async def drain(p: Profile, limit_s: float = 3600) -> float:
    assert p.engine is not None
    t0 = time.monotonic()
    while time.monotonic() - t0 < limit_s:
        jobs = p.q(lambda c: repo.job_counts(c))
        busy = p.engine.scheduler.background is not None or p.engine._learn  # pyright: ignore[reportPrivateUsage]
        if not jobs.get("queued") and not jobs.get("running") and not busy:
            break
        await asyncio.sleep(1.0)
    return round(time.monotonic() - t0, 1)


def queue_latency(p: Profile) -> list[float]:
    rows = p.q(lambda c: c.execute(
        "SELECT created_at, updated_at FROM memory_jobs WHERE status = 'done'").fetchall())  # fmt: skip
    out = []
    for a, b in rows:
        ta = datetime.fromisoformat(str(a).replace("Z", "+00:00"))
        tb = datetime.fromisoformat(str(b).replace("Z", "+00:00"))
        out.append((tb - ta).total_seconds())
    return out


async def one(model: str, size: int, pause_s: float) -> dict[str, Any]:
    llm = Counter(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1800))
    p = PerfProfile(model, llm)
    await p.start()
    await p.clean_session()
    runner_peak = 0.0
    try:
        await turn(p, "Merhaba.")
        idle = [await turn(p, SMALL_TALK[i % len(SMALL_TALK)]) for i in range(3)]
        await drain(p)
        llm.calls = dict.fromkeys(llm.calls, 0)
        during: list[float | None] = []
        t0 = time.monotonic()
        for i in range(max(1, size // 5)):
            await turn(p, message(i))
            await asyncio.sleep(pause_s)  # learning starts in the pause …
            during.append(await turn(p, SMALL_TALK[i % len(SMALL_TALK)]))  # … and is preempted
            for pid in runner_pids():
                runner_peak = max(runner_peak, footprint_mb(pid) or 0.0)
        drain_s = await drain(p)
        total_s = round(time.monotonic() - t0, 1)
        lat = queue_latency(p)
        written = p.q(lambda c: repo.count_memories(c))
        rels = p.q(lambda c: c.execute("SELECT COUNT(*) FROM memory_relationships").fetchone()[0])
        status = dict(p.engine.learner.status) if p.engine else {}
        dur = [x for x in during if x is not None]
        return {
            "size": size, "messages": max(1, size // 5), "pause_s": pause_s,
            "idle_ttft_s": statistics.median([x for x in idle if x is not None]),
            "learning_ttft_s_median": round(statistics.median(dur), 2) if dur else None,
            "learning_ttft_s_p90": round(sorted(dur)[int(0.9 * (len(dur) - 1))], 2) if dur else None,
            "learning_ttft_s_max": max(dur) if dur else None,
            "queue_latency_s_median": round(statistics.median(lat), 1) if lat else None,
            "queue_latency_s_max": round(max(lat), 1) if lat else None,
            "drain_after_last_s": drain_s, "total_s": total_s, "model_calls": dict(llm.calls),
            "memories_written": written, "relationships_written": int(rels),
            "jobs": p.q(lambda c: repo.job_counts(c)), "last_learning": status.get("refined"),
            "process_rss_peak_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1),
            "model_runner_footprint_peak_mb": runner_peak or None,
        }  # fmt: skip
    finally:
        await p.stop()
        p.remove()
        await llm.inner.aclose()


async def run(model: str, sizes: list[int], pause_s: float, path: Path) -> None:
    report: dict[str, Any] = {"model": model, "manifest": manifest(model), "rows": []}
    for n in sizes:
        row = await one(model, n, pause_s)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        report["rows"].append(row)
        text = json.dumps(report, ensure_ascii=False, indent=1) + "\n"
        await asyncio.to_thread(path.write_text, text)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:12b-it-qat")
    ap.add_argument("--sizes", default="20,100,500")
    ap.add_argument("--pause", type=float, default=9.0)
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[:/]", "_", args.model)
    path = OUT / f"perf_{name}{'_' + args.label if args.label else ''}.json"
    asyncio.run(run(args.model, [int(x) for x in args.sizes.split(",")], args.pause, path))
    print(path)


if __name__ == "__main__":
    main()
