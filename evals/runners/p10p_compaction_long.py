"""Compaction latency work: long conversations with a user who keeps writing (real Gemma).

    uv run --project core python evals/runners/p10p_compaction_long.py --model gemma4:12b-it-qat \
        --label baseline --cache-ram 2048 --gaps 6,30,60 --runs 3
    uv run --project core python evals/runners/p10p_compaction_long.py --model gemma4:12b-it-qat \
        --label baseline --quality

Production settings and engine, throwaway encrypted profiles, synthetic data. The model runs in a
private ``ollama serve`` on port 11499 with the given ``LLAMA_ARG_CACHE_RAM``: the machine's Ollama
service and its settings are not touched. The server restarts for every run.

**Long run** (40 fixed messages from an empty conversation, the same for every gap and code):
facts, then general questions, then questions about the facts. Per turn: first token, stages,
prompt tokens, shown vs stored text. Per run: message integrity from the database, context state
after every turn (a trim or an uncovered range counts as history lost), compactions, summaries,
memories, and system memory (runner RSS, used memory, pressure level, swap) sampled every 5 s.

**Quality** (``--quality``): dataset ``tr_compaction_v1`` through ``engine.compact_now``, short and
inside a long conversation, seeds 7 and 11: facts kept in the summary, of 128.

Writes evals/reports/phase10/perf/<label>_<...>.json, one file per run; an existing file is kept
and skipped, so a stopped sequence can continue.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import signal
import statistics
import subprocess
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from common import REPO, manifest
from p3_context_eval import DATA, score
from p6_sessions import Profile, Recorder
from p10s_compaction_turn import CAP, P, integrity
from p10s_compaction_turn import QUESTIONS as BASE_QUESTIONS
from p10s_compaction_turn import SEED_A, SEED_Q

from lazis.config.model import AppSection, ConversationSection, LoggingSection, Settings, StorageSection
from lazis.conversation import TurnRequest
from lazis.conversation import repository as conv_repo
from lazis.conversation.compaction import normalize
from lazis.conversation.prompts import SUMMARY_SCHEMA
from lazis.ids import utc_now_iso
from lazis.memory import repository as memory_repo
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import ChatRequest, StreamEvent

OUT = REPO / "evals" / "reports" / "phase10" / "perf"
PORT = 11499
ENDPOINT = f"http://127.0.0.1:{PORT}"
TURN_LIMIT_S = 480
ROUNDS = 40

MORE_QUESTIONS = [
    "Güneş enerjisi panelleri nasıl elektrik üretir?", "Depremlere dayanıklı bina nasıl yapılır?",
    "Kahve nasıl kavrulur, kavurma tadı nasıl etkiler?", "Bir bütçe tablosu nasıl hazırlanır?",
    "Python'da liste ile demet arasındaki fark nedir?", "Uyku düzenini iyileştirmek için neler yapılabilir?",
    "Ekmek mayası nasıl çalışır?", "Bir toplantı nasıl verimli yönetilir?",
    "Aşı bağışıklık sistemini nasıl eğitir?", "İnternet paketleri hedefe nasıl ulaşır?",
    "Evde enerji tasarrufu için neler yapılabilir?", "Bir kitabın özeti nasıl çıkarılır?",
]  # fmt: skip


def fact_messages() -> tuple[list[str], list[dict[str, Any]]]:
    """The user messages holding the dataset's facts (D1, D4, D5), and the questions about them."""
    dataset = json.loads(DATA.read_text())["dialogues"]
    facts: list[str] = []
    probes: list[dict[str, Any]] = []
    for d in dataset:
        if d["id"] not in ("D1", "D4", "D5"):
            continue
        cited = {seq for _, seq in d["summary_expect"]}
        facts += [c for i, (r, c) in enumerate(d["messages"], 1) if r == "user" and i in cited]
        probes += d["probes"]
    return facts, probes


def messages() -> tuple[list[str], list[dict[str, Any]]]:
    facts, probes = fact_messages()
    general = (BASE_QUESTIONS + MORE_QUESTIONS)[: ROUNDS - len(facts) - len(probes)]
    sent = facts + general + [p["q"] for p in probes]
    assert len(sent) == ROUNDS and len(set(sent)) == ROUNDS, (len(sent), len(set(sent)))
    return sent, probes


# ----- private runtime and system memory -----------------------------------------------------
class Server:
    def __init__(self, cache_ram: int) -> None:
        self.cache_ram = cache_ram
        self.proc: subprocess.Popen[bytes] | None = None

    async def start(self) -> None:
        env = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{PORT}", "OLLAMA_NO_CLOUD": "1",
               "LLAMA_ARG_CACHE_RAM": str(self.cache_ram)}  # fmt: skip
        self.proc = subprocess.Popen(
            ["ollama", "serve"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        llm = OllamaProvider(ENDPOINT)
        try:
            for _ in range(100):
                try:
                    await llm.list_models(refresh=True)
                    return
                except Exception:
                    await asyncio.sleep(0.2)
            raise RuntimeError("the private runtime did not start")
        finally:
            await llm.aclose()

    def stop(self) -> None:
        if self.proc is None:
            return
        self.proc.send_signal(signal.SIGTERM)
        try:
            self.proc.wait(20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(5)
        self.proc = None

    def runner_pid(self) -> int | None:
        if self.proc is None:
            return None
        out = subprocess.run(["pgrep", "-P", str(self.proc.pid)], capture_output=True, text=True).stdout
        pids = out.split()
        return int(pids[0]) if pids else None


def _sample(server: Server) -> dict[str, Any]:
    row: dict[str, Any] = {"t": time.time(), "runner_rss_mb": 0}
    pid = server.runner_pid()
    if pid is not None:
        rss = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True).stdout
        row["runner_rss_mb"] = int(rss.strip() or 0) // 1024
    vm = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    pages = {m[0]: int(m[1]) for m in re.findall(r"^(.+?):\s+(\d+)\.$", vm, re.M)}
    mb = 16384 / 1024 / 1024
    row["used_mb"] = round(
        (pages.get("Pages active", 0) + pages.get("Pages wired down", 0)
         + pages.get("Pages occupied by compressor", 0)) * mb
    )  # fmt: skip
    row["compressed_mb"] = round(pages.get("Pages occupied by compressor", 0) * mb)
    row["swapouts"] = pages.get("Swapouts", 0)
    swap = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
    used = re.search(r"used = ([\d.]+)M", swap)
    row["swap_used_mb"] = round(float(used.group(1))) if used else None
    level = subprocess.run(
        ["sysctl", "-n", "kern.memorystatus_vm_pressure_level"], capture_output=True, text=True
    ).stdout
    row["pressure_level"] = int(level.strip() or 0)  # 1 normal, 2 warning, 4 critical
    return row


async def sample_memory(server: Server, rows: list[dict[str, Any]], stop: asyncio.Event) -> None:
    while not stop.is_set():
        rows.append(await asyncio.to_thread(_sample, server))
        try:
            await asyncio.wait_for(stop.wait(), 5)
        except TimeoutError:
            pass


def memory_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    return {
        "samples": len(rows),
        "runner_rss_peak_mb": max(r["runner_rss_mb"] for r in rows),
        "used_peak_mb": max(r["used_mb"] for r in rows),
        "compressed_peak_mb": max(r["compressed_mb"] for r in rows),
        "pressure_level_max": max(r["pressure_level"] for r in rows),
        "pressure_not_normal_samples": sum(r["pressure_level"] != 1 for r in rows),
        "swap_used_start_mb": rows[0]["swap_used_mb"],
        "swap_used_peak_mb": max(r["swap_used_mb"] or 0 for r in rows),
        "swapouts_during": rows[-1]["swapouts"] - rows[0]["swapouts"],
    }


# ----- one long run ---------------------------------------------------------------------------
def context_state(p: P) -> dict[str, Any]:
    def read(c: Any) -> dict[str, Any]:
        state = conv_repo.get_context(c, p.session_id)
        summary = conv_repo.get_summary(c, state.summary_id) if state and state.summary_id else None
        covered = summary.to_seq if summary else 0
        start = state.window_start_seq if state else 1
        return {"strategy": state.strategy if state else None, "window_start": start, "summary_to": covered,
                "uncovered": max(0, start - 1 - covered)}  # fmt: skip

    return p.q(read)


async def turn(p: P, text: str) -> dict[str, Any]:
    assert p.engine is not None
    t0 = time.monotonic()
    job = p.engine.scheduler.background
    bg = None if job is None else {"kind": job.kind, "age_s": round(t0 - job.started_monotonic, 1)}
    h = await asyncio.wait_for(
        p.engine.begin_turn(TurnRequest(p.session_id, f"c-{secrets.token_hex(6)}", text, p.model)), TURN_LIMIT_S
    )  # fmt: skip
    stages: dict[str, int] = {}
    first: int | None = None
    shown, final = "", None
    errors: list[Any] = []

    async def drain() -> None:
        nonlocal first, shown, final
        async for e in p.engine.events(h):  # type: ignore[union-attr]
            now = round((time.monotonic() - t0) * 1000)
            if e["type"] == "status":
                stages.setdefault(e["stage"], now)
            elif e["type"] == "delta":
                first = now if first is None else first
                shown += str(e["text"])
            elif e["type"] == "done":
                final = e["message"]["content"]
            elif e["type"] == "error":
                errors.append(e.get("code"))

    timed_out = False
    try:
        await asyncio.wait_for(drain(), TURN_LIMIT_S)
    except TimeoutError:
        timed_out = True
    p.session_id = h.conversation.id
    last = dict(p.engine.last_turn or {})
    return {
        "user": text, "background_at_send": bg, "first_delta_ms": first, "stages": stages,
        "total_ms": round((time.monotonic() - t0) * 1000), "timed_out": timed_out, "errors": errors,
        "reply": final, "shown_equals_final": shown == final, "context": context_state(p),
        **{k: last.get(k) for k in ("ttft_ms", "context_prep_ms", "runtime_ttft_ms", "prompt_tokens", "output_tokens")},
    }  # fmt: skip


def stored_equals_shown(p: P, turns: list[dict[str, Any]]) -> bool:
    def read(c: Any) -> dict[str, str]:
        rows = c.execute(
            "SELECT seq, role, content FROM messages WHERE conversation_id = ? ORDER BY seq", (p.session_id,)
        ).fetchall()
        out: dict[str, str] = {}
        for a, b in zip(rows, rows[1:], strict=False):
            if a[1] == "user" and b[1] == "assistant":
                out[a[2]] = b[2]
        return out

    stored = p.q(read)
    return all(stored.get(t["user"]) == t["reply"] for t in turns)


async def settle(p: P, limit: float = 300) -> dict[str, Any]:
    assert p.engine is not None
    t0 = time.monotonic()
    quiet = 0
    while time.monotonic() - t0 < limit:
        counts = p.q(memory_repo.job_counts)
        idle = not counts.get("queued") and not counts.get("running")
        if idle and p.engine.scheduler.background is None and not p.engine.is_busy():
            quiet += 1
            if quiet >= 40:
                return {"settled": True, "s": round(time.monotonic() - t0 - 10, 1)}
        else:
            quiet = 0
        await asyncio.sleep(0.25)
    return {"settled": False, "s": limit}


def latency(turns: list[dict[str, Any]]) -> dict[str, Any]:
    first = [(t["first_delta_ms"] or TURN_LIMIT_S * 1000) / 1000 for t in turns]
    slow = [x > 15 for x in first]
    window = max((sum(slow[i : i + 8]) for i in range(max(1, len(slow) - 7))), default=0)
    return {
        "median_s": round(statistics.median(first), 2),
        "worst_s": round(max(first), 1),
        "over_15s": sum(slow),
        "over_15s_max_in_8": window,
        "first_token_s": [round(x, 1) for x in first],
    }


async def long_run(model: str, gap: float, cache_ram: int) -> dict[str, Any]:
    sent, probes = messages()
    server = Server(cache_ram)
    await server.start()
    llm = Recorder(OllamaProvider(ENDPOINT, first_token_timeout=600, idle_timeout=120, max_duration=1200))
    stop = asyncio.Event()
    mem: list[dict[str, Any]] = []
    sampler = asyncio.create_task(sample_memory(server, mem, stop))
    p = P(model, llm)
    n0 = len(CAP.events)
    try:
        await llm.inner.load(model, num_ctx=16384, keep_alive="10m")  # no row carries the model load
        await p.start()
        assert p.engine is not None
        session = await p.engine.start_new_session(model)
        p.session_id = session.id
        turns = []
        for i, text in enumerate(sent):
            t = await turn(p, text)
            turns.append(t)
            print(json.dumps({"i": i + 1, "first_s": round((t["first_delta_ms"] or 0) / 1000, 1),
                              "total_s": round(t["total_ms"] / 1000, 1), "tokens": t["prompt_tokens"],
                              "bg": t["background_at_send"], "stages": list(t["stages"]),
                              "ctx": t["context"]}, ensure_ascii=False), flush=True)  # fmt: skip
            await asyncio.sleep(gap)
        s = await settle(p)
        ev = [{k: v for k, v in e.items() if k != "t"} for e in CAP.events[n0:]]
        answers = {t["user"]: t["reply"] or "" for t in turns}
        scored = [{"q": q["q"], "answer": answers[q["q"]], **score(answers[q["q"]], q)} for q in probes]

        def summaries(c: Any) -> list[dict[str, Any]]:
            return [{"version": x.version, "to_seq": x.to_seq, "status": x.status, "kept": x.kept_items,
                     "dropped": x.dropped_items, "rendered": x.rendered}
                    for x in conv_repo.list_summaries(c, p.session_id)]  # fmt: skip

        return {
            "gap_s": gap, "cache_ram": cache_ram, "latency": latency(turns), "turns": turns,
            "integrity": integrity(p, sent), "stored_equals_shown": stored_equals_shown(p, turns),
            "shown_equals_final": all(t["shown_equals_final"] for t in turns), "settle": s,
            "history_uncovered_max": max(t["context"]["uncovered"] for t in turns),
            "trimmed": any(t["context"]["strategy"] == "window_only" for t in turns),
            "compactions": ev, "completed": sum(e["event"] == "compaction.completed" for e in ev),
            "failed": sum(e["event"] == "compaction.failed" for e in ev),
            "probes": scored, "probes_passed": sum(x["pass"] for x in scored), "probes_total": len(scored),
            "summaries": p.q(summaries), "memories": p.memories(),
            "memory_jobs": p.q(memory_repo.job_counts), "memory_system": memory_summary(mem),
        }  # fmt: skip
    finally:
        stop.set()
        await sampler
        await p.stop()
        p.remove()
        await llm.inner.aclose()
        server.stop()


# ----- summary quality ------------------------------------------------------------------------
class SeededRecorder(Recorder):
    """The summary request exactly as the engine builds it, with another seed."""

    def __init__(self, inner: OllamaProvider, seed: int) -> None:
        super().__init__(inner)
        self.seed = seed

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        if request.options.response_format is SUMMARY_SCHEMA:
            request = replace(request, options=replace(request.options, seed=self.seed))
        async for ev in super().stream(request):
            yield ev


@dataclass
class QualityProfile(Profile):
    keep: int = 2048

    def settings(self) -> Settings:
        return Settings(
            app=AppSection(environment="test"),
            storage=StorageSection(data_dir=self.root / "data"),
            logging=LoggingSection(directory=self.root / "logs"),
            conversation=ConversationSection(idle_compaction_delay_s=3600.0, prewarm=False, keep_recent_tokens=self.keep),
        )  # fmt: skip


async def quality_one(model: str, d: dict[str, Any], seed: int, long: bool) -> dict[str, Any]:
    llm = SeededRecorder(OllamaProvider(ENDPOINT, first_token_timeout=600, idle_timeout=120, max_duration=1200), seed)
    p = QualityProfile(model, llm, keep=2048 if long else 256)
    try:
        await p.start()
        assert p.engine is not None
        session = await p.engine.start_new_session(model)
        cid = session.id
        history = [(r, c) for r, c in d["messages"]]
        if long:  # the same facts at the start of a long conversation
            for i in range(8):
                history += [("user", SEED_Q[i % len(SEED_Q)]), ("assistant", SEED_A * 3)]

        def write(c: Any) -> None:
            with conv_repo.transaction(c):
                for role, text in history:
                    conv_repo.insert_message(c, conversation_id=cid, role=role, content=text, status="complete",
                                             now=utc_now_iso(), model=None if role == "user" else model)  # fmt: skip

        p.q(write)
        t0 = time.monotonic()
        done = await p.engine.compact_now(cid)
        seconds = round(time.monotonic() - t0, 1)
        active = next((s for s in p.q(lambda c: conv_repo.list_summaries(c, cid)) if s.status == "active"), None)
        to_seq = active.to_seq if active else 0
        rendered = active.rendered if active else ""
        expect = [x for x, seq in d["summary_expect"] if seq <= to_seq]
        missing = [x for x in expect if normalize(x) not in normalize(rendered)]
        return {"dialogue": d["id"], "seed": seed, "long": long, "done": done, "s": seconds, "to_seq": to_seq,
                "facts": len(expect), "missing": missing, "kept": active.kept_items if active else None,
                "dropped": active.dropped_items if active else None, "rendered": rendered}  # fmt: skip
    finally:
        await p.stop()
        p.remove()
        await llm.inner.aclose()


async def quality(model: str, cache_ram: int) -> dict[str, Any]:
    server = Server(cache_ram)
    await server.start()
    rows: list[dict[str, Any]] = []
    try:
        for long in (False, True):
            for seed in (7, 11):
                for d in json.loads(DATA.read_text())["dialogues"]:
                    rows.append(await quality_one(model, d, seed, long))
                    r = rows[-1]
                    print(json.dumps({k: r[k] for k in ("dialogue", "seed", "long", "s", "facts", "missing", "kept")},
                                     ensure_ascii=False), flush=True)  # fmt: skip
    finally:
        server.stop()
    facts = sum(r["facts"] for r in rows)
    lost = sum(len(r["missing"]) for r in rows)
    return {"facts": facts, "kept_facts": facts - lost, "items": sum(r["kept"] or 0 for r in rows), "rows": rows}


# ----- entry ----------------------------------------------------------------------------------
def code_id() -> str:
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout
    dirty = subprocess.run(["git", "status", "--porcelain", "core"], cwd=REPO, capture_output=True, text=True).stdout
    return head.strip() + ("+dirty" if dirty.strip() else "")


def machine_is_free() -> None:
    """Nothing else may hold the model: unload it from the service (its settings stay)."""
    app = subprocess.run(["pgrep", "-x", "LAZIS"], capture_output=True, text=True).stdout
    if app.strip():
        raise SystemExit("the LAZIS app is running; these measurements need a free machine")
    subprocess.run(["ollama", "stop", "gemma4:12b-it-qat"], capture_output=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--cache-ram", type=int, default=2048)
    ap.add_argument("--gaps", default="6,30,60")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--quality", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    machine_is_free()
    meta = {"model": args.model, "label": args.label, "code": code_id(), "manifest": manifest(args.model)}
    if args.quality:
        path = OUT / f"{args.label}_quality.json"
        if not path.exists():
            report = asyncio.run(quality(args.model, args.cache_ram))
            path.write_text(json.dumps({**meta, **report}, ensure_ascii=False, indent=1) + "\n")
        print(path)
        return
    for k in range(1, args.runs + 1):
        for gap in (float(x) for x in args.gaps.split(",")):
            path = OUT / f"{args.label}_cache{args.cache_ram}_gap{gap:g}_r{k}.json"
            if path.exists():
                continue
            report = asyncio.run(long_run(args.model, gap, args.cache_ram))
            path.write_text(json.dumps({**meta, "started_run": k, **report}, ensure_ascii=False, indent=1) + "\n")
            print(json.dumps({"path": path.name, **{x: report[x] for x in (
                "latency", "integrity", "stored_equals_shown", "history_uncovered_max", "trimmed", "completed",
                "failed", "probes_passed", "memory_system", "settle")}}, ensure_ascii=False), flush=True)  # fmt: skip


if __name__ == "__main__":
    main()
