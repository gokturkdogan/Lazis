"""Why does the model process grow? The same short conversation with learning on and off.

    uv run --project core python evals/runners/p10p_supervise.py --detach --label diag-on --run 1 \
        --runner evals/runners/p10p_memdiag_learning.py --gaps on-short \
        --out evals/reports/phase10/perf/memdiag-learning

The scenarios: ``on-short``, ``off-short`` (the light test's ten messages, 45 s apart, then five idle
minutes) and ``on-smoke``, ``off-smoke`` (a tool check). Learning is turned off only in this run's
settings, for its throwaway profile; no product code and no real profile or service changes.

Recorded on stdout, kept by the supervisor, so a stopped run still has its record:

- ``call_start`` and ``call_end``: every model call with kind, tokens, time and the process memory
  before and after it. Read with ``proc_pid_rusage``, well under a millisecond, so the reply is not
  delayed. Footprint and wired size come from the kernel; compressed memory is in the supervisor's
  ``process_memory.jsonl``.
- ``m``: process memory about once a second while it changes, which shows if it falls after a call.
- ``llama``: the runtime's own account of context checkpoints and of the prompt cache. Only these
  numbers are parsed out of its log; no other line is kept, so no message text is recorded.
- ``vmmap``: memory by region, after the last turn and after the idle time, when the runtime is idle.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from common import manifest
from p3_context_eval import score
from p10p_compaction_long import (
    ENDPOINT,
    OUT,
    PORT,
    Server,
    code_id,
    machine_is_free,
    memory_summary,
    sample_memory,
    settle,
    stored_equals_shown,
    turn,
)
from p10p_daily import (
    Events,
    Step,
    TraceRecorder,
    recall_state,
    scenario,
    typing_gap,
    uncertain_memories,
)
from p10s_compaction_turn import P, integrity

from lazis.config.model import AppSection, LoggingSection, MemorySection, Settings, StorageSection
from lazis.memory import repository as memory_repo
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import ChatRequest, GenerationDone, StreamEvent

GAP_S = 45.0
IDLE_S = {"short": 300.0, "smoke": 30.0}
SAMPLE_S = 1.0
SAMPLE_EVERY_S = 5.0
SAMPLE_CHANGE_MB = 16

LIBPROC = ctypes.CDLL("/usr/lib/libproc.dylib")
RUSAGE_INFO_V4 = 4
# rusage_info_v4: a 16-byte uuid, then 64-bit fields in this order.
RI_WIRED, RI_RESIDENT, RI_FOOTPRINT = 2 + 5, 2 + 6, 2 + 7

CREATED = re.compile(
    r"created context checkpoint (\d+) of (\d+) \(.*n_tokens = (\d+), size = ([\d.]+) MiB"
)
ERASED = re.compile(
    r"eras\w+ (?:\w+ )*context checkpoint \(.*?n_tokens = (\d+).*size = ([\d.]+) MiB"
)
CACHE = re.compile(r"cache state: (\d+) prompts, ([\d.]+) MiB \(limits: ([\d.]+) MiB")
ROOM = re.compile(
    r"making room for prompt cache entry, removing oldest entry \(size = ([\d.]+) MiB"
)
PROMPT = re.compile(r"new prompt, n_ctx_slot = (\d+), n_keep = \d+, task\.n_tokens = (\d+)")
CACHED = re.compile(r"cached n_tokens = (\d+), memory_seq_rm")


def emit(row: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(row, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def process_mb(pid: int | None) -> dict[str, int] | None:
    if pid is None:
        return None
    buf = (ctypes.c_uint64 * 64)()
    if LIBPROC.proc_pid_rusage(pid, RUSAGE_INFO_V4, buf) != 0:
        return None
    return {
        "footprint": buf[RI_FOOTPRINT] >> 20,
        "resident": buf[RI_RESIDENT] >> 20,
        "wired": buf[RI_WIRED] >> 20,
    }


class Runtime:
    """What the runtime's log says now: numbers only."""

    def __init__(self) -> None:
        self.checkpoints = 0
        self.checkpoint_limit = 0
        self.checkpoint_mib = 0.0
        self.created = 0
        self.erased = 0
        self.cache_prompts = 0
        self.cache_mib = 0.0
        self.cache_limit_mib = 0.0

    def read(self, line: str) -> None:
        row: dict[str, Any] | None = None
        if m := CREATED.search(line):
            self.checkpoints = int(m[1])
            self.checkpoint_limit, self.checkpoint_mib = int(m[2]), float(m[4])
            self.created += 1
            row = {
                "event": "checkpoint_created",
                "index": int(m[1]),
                "n_tokens": int(m[3]),
                "mib": float(m[4]),
            }
        elif m := ERASED.search(line):
            self.checkpoints = max(0, self.checkpoints - 1)
            self.erased += 1
            row = {"event": "checkpoint_erased", "n_tokens": int(m[1]), "mib": float(m[2])}
        elif m := CACHE.search(line):
            self.cache_prompts, self.cache_mib, self.cache_limit_mib = (
                int(m[1]),
                float(m[2]),
                float(m[3]),
            )
            row = {
                "event": "cache_state",
                "prompts": int(m[1]),
                "mib": float(m[2]),
                "limit_mib": float(m[3]),
            }
        elif m := ROOM.search(line):
            row = {"event": "cache_evicted", "mib": float(m[1])}
        elif m := PROMPT.search(line):
            row = {"event": "new_prompt", "n_ctx_slot": int(m[1]), "n_tokens": int(m[2])}
        elif m := CACHED.search(line):
            row = {"event": "reused_tokens", "n_tokens": int(m[1])}
        if row is not None:
            emit(
                {
                    "llama": {
                        "at": time.strftime("%H:%M:%S"),
                        **row,
                        "live_checkpoints": self.checkpoints,
                    }
                }
            )

    def state(self) -> dict[str, Any]:
        return {
            "checkpoints": self.checkpoints,
            "checkpoints_mib": round(self.checkpoints * self.checkpoint_mib),
            "cache_prompts": self.cache_prompts,
            "cache_mib": round(self.cache_mib),
        }


class DiagServer(Server):
    """The same private runtime and environment, with its log read instead of discarded."""

    def __init__(self, cache_ram: int, runtime: Runtime) -> None:
        super().__init__(cache_ram)
        self.runtime = runtime
        self._runner: int | None = None

    async def start(self) -> None:
        env = {**os.environ, "OLLAMA_HOST": f"127.0.0.1:{PORT}", "OLLAMA_NO_CLOUD": "1",
               "LLAMA_ARG_CACHE_RAM": str(self.cache_ram)}  # fmt: skip
        self.proc = subprocess.Popen(
            ["ollama", "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
        )
        threading.Thread(target=self._read_log, daemon=True).start()
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

    def _read_log(self) -> None:
        assert self.proc is not None and self.proc.stderr is not None
        for line in self.proc.stderr:
            self.runtime.read(line)

    def pid(self) -> int | None:
        """The model runner. Found once; a failed read below finds it again."""
        if self._runner is None or process_mb(self._runner) is None:
            self._runner = self.runner_pid()
        return self._runner

    def memory(self) -> dict[str, Any]:
        return {"runner": process_mb(self.pid()), **self.runtime.state()}


class DiagRecorder(TraceRecorder):
    def __init__(self, inner: OllamaProvider, server: DiagServer) -> None:
        super().__init__(inner)
        self.server = server
        self.calls_memory: list[dict[str, Any]] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        kind = self._kind(request)
        before = self.server.memory()
        emit({"call_start": {"kind": kind, "at": time.strftime("%H:%M:%S"), "memory": before}})
        t0 = time.monotonic()
        tokens: dict[str, int | None] = {}
        try:
            async for ev in super().stream(request):
                if isinstance(ev, GenerationDone):
                    tokens = {
                        "prompt_tokens": ev.metrics.prompt_tokens,
                        "output_tokens": ev.metrics.output_tokens,
                    }
                yield ev
        finally:
            after = self.server.memory()
            row = {"kind": kind, "at": time.strftime("%H:%M:%S"), "s": round(time.monotonic() - t0, 1), **tokens,
                   "memory_before": before, "memory_after": after}  # fmt: skip
            self.calls_memory.append(row)
            emit({"call_end": row})


async def watch_memory(server: DiagServer, stop: asyncio.Event) -> None:
    """Often enough to see memory fall after a call; a line only when something changed."""
    last = None
    last_at = 0.0
    while not stop.is_set():
        now = server.memory()
        fp = (now["runner"] or {}).get("footprint", 0)
        if (
            last is None
            or abs(fp - last) >= SAMPLE_CHANGE_MB
            or time.monotonic() - last_at >= SAMPLE_EVERY_S
        ):
            emit({"m": {"at": time.strftime("%H:%M:%S"), **now}})
            last, last_at = fp, time.monotonic()
        try:
            await asyncio.wait_for(stop.wait(), SAMPLE_S)
        except TimeoutError:
            pass


def model_size() -> dict[str, Any]:
    """The runtime's own figure for the loaded model."""
    try:
        with urllib.request.urlopen(f"{ENDPOINT}/api/ps", timeout=5) as r:  # noqa: S310 - localhost
            models = json.load(r).get("models") or []
    except OSError as exc:
        return {"error": type(exc).__name__}
    return {
        "models": [
            {k: m.get(k) for k in ("name", "size", "size_vram", "context_length", "expires_at")}
            for m in models
        ]
    }


def regions(pid: int | None, moment: str) -> None:
    """Memory by region type. It pauses the target briefly, so only while nothing is running."""
    if pid is None:
        return
    try:
        text = subprocess.run(
            ["vmmap", "--summary", str(pid)], capture_output=True, text=True, timeout=90
        ).stdout
    except subprocess.TimeoutExpired:
        emit({"vmmap": {"moment": moment, "error": "timeout"}})
        return
    start = text.find("REGION TYPE")
    keep = [
        re.sub(r"\s+", " ", line).strip()
        for line in text[start:].splitlines()[:70]
        if line.strip() and not line.startswith("=")
    ]
    emit({"vmmap": {"moment": moment, "lines": keep}})


class ProfileOff(P):
    """Learning off in these settings only. Everything else stays at the production default."""

    def settings(self) -> Settings:
        return Settings(
            app=AppSection(environment="test"),
            storage=StorageSection(data_dir=self.root / "data"),
            logging=LoggingSection(directory=self.root / "logs"),
            memory=MemorySection(auto_extract=False),
        )


def steps_for(name: str) -> tuple[bool, list[Step], float]:
    switch, _, length = name.partition("-")
    if switch not in ("on", "off") or length not in IDLE_S:
        raise SystemExit(f"unknown scenario {name}")
    if length == "smoke":
        return switch == "on", scenario("smoke"), IDLE_S[length]
    steps = scenario("light")
    fixed = [Step(s.text, s.kind, 0 if i == 0 else GAP_S, s.probe) for i, s in enumerate(steps)]
    return switch == "on", fixed, IDLE_S[length]


async def run(model: str, name: str, cache_ram: int) -> dict[str, Any]:
    learning_on, steps, idle_s = steps_for(name)
    runtime = Runtime()
    server = DiagServer(cache_ram, runtime)
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
    p = P(model, llm) if learning_on else ProfileOff(model, llm)
    started = time.time()
    try:
        await p.start()
        assert p.engine is not None
        session = await p.engine.start_new_session(model)
        p.session_id = session.id
        await p.engine.prepare(p.session_id, model)
        last_prepare = time.monotonic()
        emit({"model_size": {"moment": "after_load", **model_size()}})
        turns: list[dict[str, Any]] = []
        for i, step in enumerate(steps):
            last_prepare, _ = await typing_gap(p, step, last_prepare, model)
            t = await turn(p, step.text)
            t.update(kind=step.kind, gap_s=step.gap_s, at=time.strftime("%H:%M:%S"))
            if step.probe is not None:
                t["recall"] = recall_state(p, llm, step)
            turns.append(t)
            emit({"i": i + 1, "kind": step.kind, "gap_s": step.gap_s,
                  "first_s": round((t["first_delta_ms"] or 0) / 1000, 1), "total_s": round(t["total_ms"] / 1000, 1),
                  "tokens": t["prompt_tokens"], "ctx": t["context"], "memory": server.memory()})  # fmt: skip
        settled = await settle(p)
        emit({"model_size": {"moment": "after_last_turn", **model_size()}})
        regions(server.pid(), "after_last_turn")
        at_end = server.memory()
        await asyncio.sleep(idle_s)
        after_idle = server.memory()
        emit({"idle": {"seconds": idle_s, "before": at_end, "after": after_idle}})
        regions(server.pid(), "after_idle")
        answers = {t["user"]: t["reply"] or "" for t in turns}
        scored = [{"q": s.text, "answer": answers[s.text], **score(answers[s.text], s.probe)}
                  for s in steps if s.probe is not None]  # fmt: skip
        memories = p.memories()
        totals: dict[str, dict[str, float]] = {}
        for c in llm.calls:
            row = totals.setdefault(
                c["kind"], {"calls": 0, "seconds": 0.0, "prompt_tokens": 0, "output_tokens": 0}
            )
            row["calls"] += 1
            row["seconds"] = round(row["seconds"] + c["s"], 1)
            row["prompt_tokens"] += c.get("prompt_tokens") or 0
            row["output_tokens"] += c.get("output_tokens") or 0
        return {
            "scenario": name, "learning": learning_on, "cache_ram": cache_ram,
            "minutes": round((time.time() - started) / 60, 1), "steps": len(steps), "gap_s": GAP_S, "idle_s": idle_s,
            "first_token_s": [round((t["first_delta_ms"] or 0) / 1000, 2) for t in turns],
            "turns": turns, "model_call_totals": totals, "model_calls": llm.calls, "calls_memory": llm.calls_memory,
            "runtime": {"checkpoints_created": runtime.created, "checkpoints_erased": runtime.erased,
                        "checkpoint_limit": runtime.checkpoint_limit, "checkpoint_mib": runtime.checkpoint_mib,
                        "cache_limit_mib": runtime.cache_limit_mib, **runtime.state()},
            "memory_at_last_turn": at_end, "memory_after_idle": after_idle, "memory_system": memory_summary(mem),
            "settle": settled, "integrity": integrity(p, [s.text for s in steps]),
            "stored_equals_shown": stored_equals_shown(p, turns), "events": events.rows,
            "probes": scored, "memories": memories, "uncertain_memories": uncertain_memories(memories),
            "memory_jobs": p.q(memory_repo.job_counts),
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
    ap.add_argument("--gaps", required=True, help="on-short, off-short, on-smoke or off-smoke")
    ap.add_argument("--runs", type=int, default=1)
    a = ap.parse_args()
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    out = Path(os.environ.get("LAZIS_EVAL_OUT", OUT / "memdiag-learning"))
    out.mkdir(parents=True, exist_ok=True)
    machine_is_free()
    path = out / f"{a.label}_cache{a.cache_ram}_gap{a.gaps}_r{a.runs}.json"
    if path.exists():
        return
    meta = {"model": a.model, "label": a.label, "code": code_id(), "manifest": manifest(a.model)}
    report = asyncio.run(run(a.model, a.gaps, a.cache_ram))
    path.write_text(json.dumps({**meta, **report}, ensure_ascii=False, indent=1) + "\n")
    emit(
        {"path": path.name, "minutes": report["minutes"], "first_token_s": report["first_token_s"]}
    )


if __name__ == "__main__":
    main()
