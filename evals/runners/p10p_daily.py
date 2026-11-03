"""Daily use on the real machine: light, medium and heavy conversations (real Gemma, current code).

    uv run --project core python evals/runners/p10p_supervise.py --detach --label daily --run 1 \
        --runner evals/runners/p10p_daily.py --gaps light --out evals/reports/phase10/perf/daily \
        --start-footprint-mb 40000 --start-swap-mb 40000 --run-limit 14400

Scenarios and targets: docs/COMPACTION_BASELINE_REPORT.md §8–9. Unlike the 40-message endurance run,
the time between messages is the point, other apps stay open (the owner keeps them open; nothing here
closes anything), no model is loaded in advance, and typing is simulated: the interface asks to warm
the prompt when a conversation opens and on input, at most once every 30 s.

Production settings and engine, throwaway encrypted profile, synthetic data, private runtime. One
line per turn, per model call and per engine event on stdout (kept by the supervisor), so a stopped
run still has its record; the report is written only when a run completes.

Per run: first token, cold starts, waits inside a turn, compactions, every model call by kind,
memory per system sample, messages and their order, shown and stored text, memories, uncertain
facts stored as certain (REL-001), facts per summary version, and for each question whether the
fact was in the summary, in memory and in the prompt at that moment (REL-002).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import statistics
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from common import manifest
from p3_context_eval import DATA, score
from p6_sessions import Recorder
from p10p_compaction_long import (
    ENDPOINT,
    MORE_QUESTIONS,
    OUT,
    TURN_LIMIT_S,
    Server,
    code_id,
    fact_messages,
    machine_is_free,
    memory_summary,
    sample_memory,
    settle,
    stored_equals_shown,
    turn,
)
from p10s_compaction_turn import CAP, P, integrity
from p10s_compaction_turn import QUESTIONS as BASE_QUESTIONS

from lazis.conversation import learning
from lazis.conversation import repository as conv_repo
from lazis.conversation.compaction import normalize
from lazis.conversation.prompts import SUMMARY_SCHEMA
from lazis.memory import repository as memory_repo
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import ChatRequest, GenerationDone, StreamEvent

PREPARE_INTERVAL_S = 30  # the interface's PREPARE_INTERVAL_MS
TYPING_SHORT_S = 6
TYPING_LONG_S = 15
HEDGES = ("galiba", "belki", "sanırım", "ihtimal", "kesin değil", "kesinleş", "belli değil", "tahmin",
          "olabilir", "söyleniyor", "muhtemel", "henüz", "karar vermedi", "gidebil", "taşınabil")  # fmt: skip

# Names and places in neither the prompts nor the datasets (checked when these were chosen).
EXTRA_UNCERTAIN = {
    "Kadir": ("Kayınbiraderim Kadir belki ocakta Kastamonu'ya taşınır, daha karar vermedi.",
              {"q": "Kadir nereye taşınıyordu? Kısaca yaz.", "expect_all": ["kastamonu"],
               "expect_any": ["belki", "kesin değil", "karar vermedi", "belli değil", "henüz", "olabilir"]}),
    "Gülay": ("Yeğenim Gülay sanırım gelecek ay Sivas'ta işe başlayacak, henüz belli değil.",
              {"q": "Gülay nerede işe başlıyordu? Kısaca yaz.", "expect_all": ["sivas"],
               "expect_any": ["sanırım", "kesin değil", "belli değil", "henüz", "belki", "olabilir"]}),
}  # fmt: skip
SHORT = [
    "Günaydın, nasılsın?", "Teşekkürler, çok işime yaradı.", "Bugün biraz yorgunum.",
    "Akşama ne pişirsem, kısa bir fikir verir misin?", "Kahve molası verdim.", "Hava bugün çok güzel.",
]  # fmt: skip
FACT_OF_PROBE = {
    "Mehmet": "İzmir", "Restoran": "vejetaryen", "Kadir": "Kastamonu", "Gülay": "Sivas", "Planlama": "perşembe",
    "Pamuk": "komşu", "Patronumla": "9:30", "Komşum": "cumartesi", "Uçuşumuz": "07:45", "Antalya": "Kaş",
    "Nakliye": "nakliye", "Araba": "otobüs",
}  # fmt: skip
STALE = {"salı": "planlama toplantısı", "antalya": "tatil yeri", "9:00": "toplantı saati"}


@dataclass(frozen=True)
class Step:
    text: str
    kind: str  # fact, uncertain, short, general, probe
    gap_s: float  # after the reply to the previous message
    probe: dict[str, Any] | None = None


def _gaps(n: int, low: float, high: float, rng: random.Random) -> list[float]:
    return [round(rng.uniform(low, high)) for _ in range(n)]


def scenario(name: str) -> list[Step]:
    """Fixed for every run and every code version."""
    facts, probes = fact_messages()
    by_q = {p["q"].split()[0].strip("'’"): p for p in probes}
    extra = {k: v for k, v in EXTRA_UNCERTAIN.items()}
    general = BASE_QUESTIONS + MORE_QUESTIONS
    rng = random.Random(f"lazis-daily-{name}")
    q = lambda *keys: [by_q[k] for k in keys if k in by_q]  # noqa: E731
    mehmet = facts[3]

    def kinds(items: list[str], kind: str) -> list[tuple[str, str, dict[str, Any] | None]]:
        return [(x, "uncertain" if kind == "fact" and x == mehmet else kind, None) for x in items]

    if name == "smoke":
        body = kinds([facts[0], mehmet], "fact") + kinds(SHORT[:1], "short")
        ask = q("Mehmet")
        gaps: list[float] = [5, 5, 5]
    elif name == "light":
        mix = kinds([facts[0], mehmet, facts[11]], "fact") + kinds(SHORT[:4], "short") + kinds(general[:1], "general")
        body, ask = _mixed(mix, rng), q("Mehmet", "Restoran")
        gaps = _gaps(9, 120, 300, rng)
    elif name == "medium":
        chosen = [facts[0], facts[2], mehmet, facts[5], facts[6], facts[8], facts[11]]
        mix = kinds(chosen, "fact") + [(extra["Kadir"][0], "uncertain", None)]
        mix += kinds(SHORT[:5], "short") + kinds(general[:7], "general")
        body = _mixed(mix, rng)
        ask = [*q("Mehmet", "Planlama", "Patronumla", "Restoran"), extra["Kadir"][1]]
        gaps = _gaps(24, 30, 300, rng)
        gaps[8] = gaps[17] = 900
        gaps = [g if g == 900 else round(g * 0.3 + 30) for g in gaps]  # 30–120 s, about an hour in all
    elif name == "heavy":
        mix = kinds(facts, "fact") + [(extra[k][0], "uncertain", None) for k in extra]
        mix += kinds(SHORT[:4], "short") + kinds(general[:22], "general")
        body = _mixed(mix, rng)
        ask = [*probes, extra["Kadir"][1], extra["Gülay"][1]][:10]
        gaps = _gaps(49, 15, 60, rng)
        for at, pause in ((9, 300), (14, 600), (18, 600), (27, 900), (36, 600), (43, 600)):
            gaps[at] = pause
    else:
        raise SystemExit(f"unknown scenario {name}")
    rows = [*body, *[(p["q"], "probe", p) for p in ask]]
    assert len(rows) == len(gaps) + 1, (name, len(rows), len(gaps))
    steps = [Step(t, k, 0 if i == 0 else gaps[i - 1], pr) for i, (t, k, pr) in enumerate(rows)]
    assert len({s.text for s in steps}) == len(steps), "a repeated message would break the checks"
    return steps


def _mixed(rows: list[tuple[str, str, dict[str, Any] | None]], rng: random.Random) -> list[Any]:
    """Facts keep their order; the other messages fall between them."""
    facts = [r for r in rows if r[1] in ("fact", "uncertain")]
    other = [r for r in rows if r[1] not in ("fact", "uncertain")]
    out = list(facts)
    for r in other:
        out.insert(rng.randint(1, len(out)), r)
    return out


class TraceRecorder(Recorder):
    """The production provider, with every model call recorded: kind, time, tokens, how it ended."""

    def __init__(self, inner: OllamaProvider) -> None:
        super().__init__(inner)
        self.calls: list[dict[str, Any]] = []

    def _kind(self, request: ChatRequest) -> str:
        fmt = request.options.response_format
        if fmt is SUMMARY_SCHEMA:
            return "compaction"
        if fmt is learning.SCHEMA:
            return "extraction"
        if request.request_id.endswith("-memory"):
            return "memory_command"
        return "prewarm" if request.options.max_tokens == 1 else "reply"

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        t0 = time.monotonic()
        row: dict[str, Any] = {"kind": self._kind(request), "at": time.strftime("%H:%M:%S"), "ended": "abandoned"}
        try:
            async for ev in super().stream(request):
                if isinstance(ev, GenerationDone):
                    row.update(prompt_tokens=ev.metrics.prompt_tokens, output_tokens=ev.metrics.output_tokens,
                               ended="complete")  # fmt: skip
                yield ev
        except BaseException as exc:
            row["ended"] = type(exc).__name__
            raise
        finally:
            row["s"] = round(time.monotonic() - t0, 1)
            self.calls.append(row)
            print(json.dumps({"call": row}, ensure_ascii=False), flush=True)

    async def load(self, *args: Any, **kwargs: Any) -> Any:
        t0 = time.monotonic()
        try:
            return await self.inner.load(*args, **kwargs)
        finally:
            row = {"kind": "load", "at": time.strftime("%H:%M:%S"), "ended": "complete",
                   "s": round(time.monotonic() - t0, 1)}  # fmt: skip
            self.calls.append(row)
            print(json.dumps({"call": row}, ensure_ascii=False), flush=True)


class Events(logging.Handler):
    """Engine events a user's wait depends on; no message content is in them."""

    NAMES = ("memory.extraction", "prewarm.", "compaction.", "context.trimmed", "memory.request")

    def __init__(self) -> None:
        super().__init__(logging.INFO)
        self.rows: list[dict[str, Any]] = []

    def emit(self, record: logging.LogRecord) -> None:
        name = record.getMessage()
        if any(name.startswith(n) for n in self.NAMES):
            fields = getattr(record, "lazis_fields", None) or {}
            row = {"event": name, "at": time.strftime("%H:%M:%S"),
                   **{k: v for k, v in fields.items() if k != "conversation_id"}}  # fmt: skip
            self.rows.append(row)
            print(json.dumps(row, ensure_ascii=False, default=str), flush=True)


def hedged(text: str) -> bool:
    t = normalize(text)
    return any(normalize(h) in t for h in HEDGES)


def uncertain_memories(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """REL-001: what was stored about the people spoken of with uncertainty. Automatic reading only."""
    out = []
    for name in ("Mehmet", *EXTRA_UNCERTAIN):
        for m in memories:
            if name in f"{m['about']} {m['content']}":
                out.append({"name": name, "content": m["content"], "predicate": m["predicate"],
                            "certain": not hedged(m["content"])})  # fmt: skip
    return out


def fact_words(steps: list[Step]) -> list[str]:
    dataset = json.loads(DATA.read_text())["dialogues"]
    said = " ".join(normalize(s.text) for s in steps if s.kind in ("fact", "uncertain"))
    words = [w for d in dataset if d["id"] in ("D1", "D4", "D5") for w, _ in d["summary_expect"]]
    words += ["Kastamonu", "Sivas"]
    return sorted({w for w in words if normalize(w) in said})


def retention(summaries: list[dict[str, Any]], words: list[str]) -> list[dict[str, Any]]:
    """Facts per summary version. A fact counts only once its message is inside the summary."""
    rows, seen = [], set()
    for s in summaries:
        text = normalize(s["rendered"])
        present = {w for w in words if normalize(w) in text}
        lost = sorted(seen - present)
        seen |= present
        rows.append({"version": s["version"], "to_seq": s["to_seq"], "present": len(present), "lost_since_earlier": lost,
                     "silent": bool(lost) and not s["dropped"], "kept": s["kept"], "dropped": s["dropped"]})  # fmt: skip
    return rows


def recall_state(p: P, llm: TraceRecorder, step: Step) -> dict[str, Any]:
    """REL-002: at the moment of the question, where the fact was."""
    word = next((v for k, v in FACT_OF_PROBE.items() if step.text.startswith(k)), "")
    key = normalize(word)

    def active(c: Any) -> str:
        state = conv_repo.get_context(c, p.session_id)
        summary = conv_repo.get_summary(c, state.summary_id) if state and state.summary_id else None
        return summary.rendered if summary else ""

    summary = normalize(p.q(active))
    memories = normalize(" ".join(m["content"] for m in p.memories()))
    sent = llm.last_chat.messages if llm.last_chat else []
    last = normalize(sent[-1].content) if sent else ""
    question = normalize(step.text)
    return {"fact": word, "in_summary": bool(key) and key in summary, "in_memory": bool(key) and key in memories,
            "in_prompt_note": bool(key) and key in last.replace(question, ""),
            "in_prompt": bool(key) and any(key in normalize(m.content) for m in sent)}  # fmt: skip


async def typing_gap(p: P, step: Step, last_prepare: float, model: str) -> tuple[float, str | None]:
    """The time before a message: the last part is typing, which may ask to warm the prompt."""
    typing = min(step.gap_s, TYPING_SHORT_S if step.kind == "short" else TYPING_LONG_S)
    await asyncio.sleep(step.gap_s - typing)
    state = None
    if time.monotonic() - last_prepare >= PREPARE_INTERVAL_S:
        assert p.engine is not None
        state = (await p.engine.prepare(p.session_id, model)).get("state")
        last_prepare = time.monotonic()
    await asyncio.sleep(typing)
    return last_prepare, state


def first_token_stats(turns: list[dict[str, Any]]) -> dict[str, Any]:
    first = [(t["first_delta_ms"] or TURN_LIMIT_S * 1000) / 1000 for t in turns]
    ordered = sorted(first)
    slow = [x > 15 for x in first]
    return {
        "median_s": round(statistics.median(first), 2),
        "p95_s": round(ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))], 2),
        "worst_s": round(max(first), 1),
        "over_15s": sum(slow),
        "over_15s_max_in_8": max((sum(slow[i : i + 8]) for i in range(max(1, len(slow) - 7))), default=0),
        "first_token_s": [round(x, 1) for x in first],
    }


def longest_warning_s(rows: list[dict[str, Any]]) -> int:
    best, since = 0.0, None
    for r in rows:
        if r["pressure_level"] >= 2:
            since = r["t"] if since is None else since
            best = max(best, r["t"] - since)
        else:
            since = None
    return round(best)


TARGETS = {
    "light": {"median_s": 1.5, "p95_s": 3, "worst_s": 5, "cold_s": 10, "swap_gb": 2, "warning_min": 1, "inturn": 0},
    "medium": {"median_s": 2, "p95_s": 6, "worst_s": 15, "cold_s": 10, "swap_gb": 4, "warning_min": 5, "inturn": 0},
    "heavy": {"median_s": 3, "p95_s": 15, "worst_s": 45, "cold_s": 10, "swap_gb": 6, "warning_min": 10, "inturn": None},
}  # fmt: skip


def judge(name: str, lat: dict[str, Any], turns: list[dict[str, Any]], mem: dict[str, Any], warn: int) -> dict[str, Any]:
    t = TARGETS.get(name)
    if t is None:
        return {}
    cold = [x["first_delta_ms"] / 1000 for x in turns if x["cold"] and x["first_delta_ms"]]
    waits = [x for x in turns if "compacting" in x["stages"]]
    swap = (mem["swap_used_peak_mb"] - mem["swap_used_start_mb"]) / 1024
    out = {
        "median": lat["median_s"] <= t["median_s"], "p95": lat["p95_s"] <= t["p95_s"], "worst": lat["worst_s"] <= t["worst_s"],
        "cold": all(x <= t["cold_s"] for x in cold), "critical": mem["pressure_level_max"] < 4,
        "swap": swap <= t["swap_gb"], "warning": warn <= t["warning_min"] * 60,
        "in_turn_compaction": (not waits) if t["inturn"] == 0 else all(
            (x["first_delta_ms"] or 0) / 1000 <= 45 for x in waits),
    }  # fmt: skip
    return {"passed": out, "cold_first_token_s": [round(x, 1) for x in cold], "swap_growth_gb": round(swap, 1),
            "in_turn_compactions": len(waits), "longest_warning_s": warn}  # fmt: skip


async def run(model: str, name: str, cache_ram: int) -> dict[str, Any]:
    steps = scenario(name)
    server = Server(cache_ram)
    await server.start()
    llm = TraceRecorder(OllamaProvider(ENDPOINT, first_token_timeout=600, idle_timeout=120, max_duration=1200))
    stop = asyncio.Event()
    mem: list[dict[str, Any]] = []
    sampler = asyncio.create_task(sample_memory(server, mem, stop))
    events = Events()
    logging.getLogger("lazis").addHandler(events)
    p = P(model, llm)
    n0 = len(CAP.events)
    started = time.time()
    try:
        await p.start()
        assert p.engine is not None
        session = await p.engine.start_new_session(model)
        p.session_id = session.id
        await p.engine.prepare(p.session_id, model)  # opening the app; no model loaded before this
        last_prepare = time.monotonic()
        turns: list[dict[str, Any]] = []
        for i, step in enumerate(steps):
            loaded_before = model in {m.name for m in await llm.loaded_models()}
            last_prepare, prep = await typing_gap(p, step, last_prepare, model)
            t = await turn(p, step.text)
            t.update(kind=step.kind, gap_s=step.gap_s, prepare_on_typing=prep,
                     cold=i == 0 or not loaded_before, at=time.strftime("%H:%M:%S"))  # fmt: skip
            if step.probe is not None:
                t["recall"] = recall_state(p, llm, step)
            turns.append(t)
            print(json.dumps({"i": i + 1, "kind": step.kind, "gap_s": step.gap_s, "cold": t["cold"],
                              "first_s": round((t["first_delta_ms"] or 0) / 1000, 1),
                              "total_s": round(t["total_ms"] / 1000, 1), "tokens": t["prompt_tokens"],
                              "bg": t["background_at_send"], "stages": list(t["stages"]), "ctx": t["context"],
                              "recall": t.get("recall")}, ensure_ascii=False), flush=True)  # fmt: skip
        s = await settle(p)
        ev = [{k: v for k, v in e.items() if k != "t"} for e in CAP.events[n0:]]
        sent = [x.text for x in steps]
        answers = {t["user"]: t["reply"] or "" for t in turns}
        scored = [{"q": x.text, "answer": answers[x.text], **score(answers[x.text], x.probe)}
                  for x in steps if x.probe is not None]  # fmt: skip

        def summaries(c: Any) -> list[dict[str, Any]]:
            return [{"version": x.version, "to_seq": x.to_seq, "status": x.status, "kept": x.kept_items,
                     "dropped": x.dropped_items, "rendered": x.rendered}
                    for x in conv_repo.list_summaries(c, p.session_id)]  # fmt: skip

        lat = first_token_stats(turns)
        system = memory_summary(mem)
        warn = longest_warning_s(mem)
        memories = p.memories()
        rows = p.q(summaries)
        totals: dict[str, dict[str, float]] = {}
        for c in llm.calls:
            row = totals.setdefault(c["kind"], {"calls": 0, "complete": 0, "seconds": 0.0, "prompt_tokens": 0})
            row["calls"] += 1
            row["complete"] += c["ended"] == "complete"
            row["seconds"] = round(row["seconds"] + c["s"], 1)
            row["prompt_tokens"] += c.get("prompt_tokens") or 0
        jobs = p.q(memory_repo.job_counts)
        return {
            "scenario": name, "cache_ram": cache_ram, "minutes": round((time.time() - started) / 60, 1),
            "steps": len(steps), "latency": lat, "targets": judge(name, lat, turns, system, warn), "turns": turns,
            "integrity": integrity(p, sent), "stored_equals_shown": stored_equals_shown(p, turns),
            "shown_equals_final": all(t["shown_equals_final"] for t in turns), "settle": s,
            "history_uncovered_max": max(t["context"]["uncovered"] for t in turns),
            "trimmed": any(t["context"]["strategy"] == "window_only" for t in turns),
            "compactions": ev, "completed": sum(e["event"] == "compaction.completed" for e in ev),
            "failed": sum(e["event"] == "compaction.failed" for e in ev),
            "model_calls": llm.calls, "model_call_totals": totals, "events": events.rows,
            "probes": scored, "probes_passed": sum(x["pass"] for x in scored), "probes_total": len(scored),
            "summaries": rows, "retention": retention(rows, fact_words(steps)), "fact_words": fact_words(steps),
            "memories": memories, "uncertain_memories": uncertain_memories(memories),
            "stale_values_in_memories": [{"word": w, "of": STALE[w], "content": m["content"], "status": m["status"]}
                                         for m in memories for w in STALE if w in m["content"].casefold()],
            "memory_jobs": jobs, "memory_complete": not jobs.get("queued") and not jobs.get("running"),
            "memory_system": system, "longest_warning_s": warn,
        }  # fmt: skip
    finally:
        stop.set()
        await sampler
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
    ap.add_argument("--gaps", required=True, help="one scenario: smoke, light, medium or heavy")
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args()
    out = Path(os.environ.get("LAZIS_EVAL_OUT", OUT / "daily"))
    out.mkdir(parents=True, exist_ok=True)
    machine_is_free()
    path = out / f"{a.label}_cache{a.cache_ram}_gap{a.gaps}_r{a.runs}.json"
    if path.exists():
        return
    meta = {"model": a.model, "label": a.label, "code": code_id(), "manifest": manifest(a.model)}
    report = asyncio.run(run(a.model, a.gaps, a.cache_ram))
    path.write_text(json.dumps({**meta, **report}, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({"path": path.name, "minutes": report["minutes"], "latency": report["latency"]}), flush=True)


if __name__ == "__main__":
    main()
