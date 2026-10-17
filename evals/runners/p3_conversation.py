"""Phase 3 conversation-engine performance on the real runtime (PHASE_3_REPORT §7).

    uv run --project core python evals/runners/p3_conversation.py --model gemma4:12b-it-qat

Drives the production ConversationEngine (prompt assembler, token budget, compaction,
pre-warming, scheduler) against a throwaway encrypted database (random in-memory key,
temporary directory, deleted afterwards) and the local Ollama runtime. Synthetic Turkish
histories only. Every TTFT is measured the way the user sees it: from submitting the turn to
the first streamed character, and every row records the total input context the model
received (``prompt_tokens``) and whether the engine expected a warm or cold cache.

Scenarios: new empty conversation; 2K/4K/8K/12K histories (cold, after pre-warm, sent while
the pre-warm runs, warm); first message after an app restart; after a model reload; switching
between conversations; first message after compaction. Writes
evals/reports/phase3/conversation_perf.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from common import REPO, footprint_mb, manifest, runner_pids, summarize
from perf import filler

from lazis.config.model import (
    AppSection,
    ConversationSection,
    LoggingSection,
    ModelsSection,
    Settings,
    StorageSection,
)
from lazis.conversation import ConversationEngine, TurnRequest, repository
from lazis.ids import utc_now_iso
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import ChatMessage, ChatRequest, GenerationDone, GenerationOptions
from lazis.security.secrets import SecretBytes
from lazis.storage import StorageHandle, open_storage

OUT = REPO / "evals" / "reports" / "phase3"
SIZES = (2000, 4000, 8000, 12000)
SHORT_TURNS = [
    "Peki bunu kısaca özetler misin?",
    "Bugün akşam için ne önerirsin?",
    "Sence en önemli nokta hangisiydi?",
    "Tamam, teşekkürler. Bir de kısa bir hatırlatma notu yazar mısın?",
    "Bunu yarın sabah yapsam olur mu?",
    "Hafta sonu için de benzer bir plan yapabilir miyiz?",
]


def _activate(conn: repository.Connection, conversation_id: str) -> None:
    with repository.transaction(conn):
        active = repository.get_active_session(conn)
        if active is None or active.id != conversation_id:
            repository.activate_session(conn, conversation_id)


class Bench:
    def __init__(
        self, model: str, root: Path, *, compact_at: int, prewarm: bool = True, idle_delay: float = 3600.0
    ) -> None:
        self.model = model
        self.root = root
        self.key = SecretBytes(secrets.token_bytes(32))
        self.compact_at = compact_at
        self.prewarm = prewarm
        self.idle_delay = idle_delay
        self.llm = OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200)
        self.storage: StorageHandle | None = None
        self.engine: ConversationEngine | None = None
        self.counter = 0
        self._overhead: int | None = None

    def settings(self) -> Settings:
        return Settings(
            app=AppSection(environment="test"),
            storage=StorageSection(data_dir=self.root / "data"),
            logging=LoggingSection(directory=self.root / "logs"),
            # Replies capped at 200 tokens to keep runs short; TTFT does not depend on the cap.
            models=ModelsSection(max_output_tokens=200),
            conversation=ConversationSection(
                compact_at_tokens=self.compact_at,
                idle_compaction_delay_s=self.idle_delay,  # compaction only where a scenario wants it
                prewarm=self.prewarm,
            ),
        )

    async def open(self) -> ConversationEngine:
        self.storage = open_storage(self.settings().storage, self.key, app_version="bench")
        self.engine = ConversationEngine(
            db=self.storage.db, get_llm=lambda: self.llm, settings=self.settings()
        )
        await self.engine.ensure_started()
        return self.engine

    async def close(self) -> None:
        if self.engine is not None:
            await self.engine.close()
        if self.storage is not None:
            self.storage.db.close()
        self.engine = None
        self.storage = None

    async def count(self, role: str, text: str) -> int:
        """The runtime's token count for one message incl. its chat-template tokens (what
        the engine records for messages it created itself)."""
        if self._overhead is None:
            self._overhead = await self._prompt_tokens(role, "a") - 1
        return await self._prompt_tokens(role, text) - self._overhead

    async def _prompt_tokens(self, role: str, text: str) -> int:
        assert self.engine is not None
        self.counter += 1
        request = ChatRequest(
            model=self.model,
            messages=[ChatMessage(role, text)] if role == "user" else [ChatMessage("user", "."), ChatMessage(role, text)],
            options=GenerationOptions(num_ctx=self.engine.num_ctx, max_tokens=1, keep_alive="10m"),
            request_id=f"count-{self.counter}",
        )
        tokens = 0
        async for event in self.llm.stream(request):
            if isinstance(event, GenerationDone) and event.metrics.prompt_tokens:
                tokens = event.metrics.prompt_tokens
        return tokens

    async def seed(self, tokens: int, rng: random.Random, *, counted: bool = True) -> str:
        """A conversation with ~``tokens`` of synthetic history, as if it were opened later.
        ``counted``: each message carries the runtime's own token count, as messages created
        through the engine do. Without counts (an imported conversation) the engine must use
        its conservative estimate."""
        assert self.storage is not None
        now = utc_now_iso()
        pairs: list[tuple[str, str]] = []
        used = 0
        while used < tokens:
            pairs.append(("user", f"Not {rng.randrange(10**6)}: " + filler(300, rng)))
            pairs.append(("assistant", "Anladım. " + filler(150, rng)))
            used += 450
        counts: list[int | None] = [None] * len(pairs)
        if counted:
            counts = [await self.count(role, text) for role, text in pairs]

        def write(conn: repository.Connection) -> str:
            with repository.transaction(conn):
                # One active session at a time (ADR-0011): seeded sessions start archived and
                # are activated when a turn is sent to them.
                conv = repository.insert_conversation(
                    conn, title=f"bench {tokens}", model=self.model, now=now, status="archived"
                )
                for (role, text), n in zip(pairs, counts, strict=True):
                    repository.insert_message(
                        conn,
                        conversation_id=conv.id,
                        role=role,  # type: ignore[arg-type]
                        content=text,
                        status="complete",
                        now=now,
                        context_note="[Mesaj zamanı: 17 Ekim 2026 Cumartesi 14:32]" if role == "user" else None,
                        token_count=n,
                        token_source="runtime" if n is not None else None,
                    )
                return conv.id

        return self.storage.db.run_sync(write)

    async def evict(self) -> None:
        """Replace the runtime's cached prefix with unrelated text (another app, another chat)."""
        assert self.engine is not None
        self.counter += 1
        request = ChatRequest(
            model=self.model,
            messages=[ChatMessage("user", f"Rastgele {secrets.token_hex(8)}: tek kelime yaz.")],
            options=GenerationOptions(num_ctx=self.engine.num_ctx, max_tokens=1, keep_alive="10m"),
            request_id=f"evict-{self.counter}",
        )
        async for _ in self.llm.stream(request):
            pass
        self.engine.scheduler.cache = None

    async def turn(self, conversation_id: str | None, text: str) -> dict[str, Any]:
        assert self.engine is not None and self.storage is not None
        if conversation_id is not None:
            # Since ADR-0011 only the active session takes turns; switching = activating.
            self.storage.db.run_sync(
                lambda c: _activate(c, conversation_id)  # type: ignore[arg-type]
            )
        self.counter += 1
        t0 = time.perf_counter()
        handle = await self.engine.begin_turn(
            TurnRequest(conversation_id, f"bench-{self.counter:06d}-{secrets.token_hex(3)}", text, self.model)
        )
        first: float | None = None
        stages: list[str] = []
        expected: str | None = None
        estimate: int | None = None
        result: dict[str, Any] = {}
        async for event in self.engine.events(handle):
            if event["type"] == "status":
                stages.append(str(event["stage"]))
                if event["stage"] == "processing_context":
                    expected = str(event.get("cache"))
                    estimate = event.get("context_tokens")  # type: ignore[assignment]
            elif event["type"] == "delta" and first is None:
                first = time.perf_counter() - t0
            elif event["type"] in ("done", "error", "cancelled"):
                result = event
        total = time.perf_counter() - t0
        prompt = result.get("context", {}).get("prompt_tokens") if result.get("type") == "done" else None
        return {
            "conversation_id": handle.conversation.id,
            "ttft_s": None if first is None else round(first, 3),
            "total_s": round(total, 3),
            "output_tokens": (result.get("message") or {}).get("metrics", {}).get("output_tokens")
            if result.get("type") == "done"
            else None,
            "outcome": result.get("type"),
            "stages": stages,
            "cache_expected": expected,
            "estimated_tokens": estimate,
            "prompt_tokens": prompt,
        }

    async def prepare_and_wait(self, conversation_id: str | None) -> dict[str, Any]:
        assert self.engine is not None
        t0 = time.perf_counter()
        state = await self.engine.prepare(conversation_id, self.model)
        job = self.engine.scheduler.background
        if job is not None and job.task is not None:
            await job.task
        return {"state": state.get("state"), "prewarm_s": round(time.perf_counter() - t0, 3)}

    async def loaded_size_gb(self) -> float | None:
        for m in await self.llm.loaded_models():
            if m.name == self.model:
                return round(m.size_bytes / 1e9, 2)
        return None


def runner_footprint_gb() -> float | None:
    """phys_footprint of Ollama's model runner (weights, KV, compute and llama.cpp's host-RAM
    prompt cache all count here on Apple Silicon)."""
    vals = [footprint_mb(pid) for pid in runner_pids()]
    vals = [v for v in vals if v]
    return round(sum(vals) / 1024, 2) if vals else None


async def run(model: str, reps: int, label: str) -> dict[str, Any]:
    rng = random.Random(20261017)
    root = Path(tempfile.mkdtemp(prefix="lazis-p3-bench-"))
    report: dict[str, Any] = {"label": label, "manifest": manifest(model), "scenarios": {}}
    scen = report["scenarios"]
    memory: list[dict[str, Any]] = []
    report["memory"] = memory

    def sample(tag: str) -> None:
        memory.append({"at": tag, "runner_gb": runner_footprint_gb()})

    try:
        bench = Bench(model, root, compact_at=13000)
        engine = await bench.open()
        # A fresh runner: unloading kills it, which also clears llama.cpp's host prompt cache.
        await bench.llm.unload(model)
        await asyncio.sleep(2)
        await bench.llm.load(model, num_ctx=engine.num_ctx, keep_alive="10m")
        report["num_ctx"] = engine.num_ctx
        report["hard_limit"] = engine.budget.hard_limit
        report["resident_gb_start"] = await bench.loaded_size_gb()
        sample("fresh runner")

        # 1. New empty conversation: the fixed system prompt is new to the runner only once.
        scen["new_conversation_first_ever"] = [await bench.turn(None, "Merhaba, bugün plan yapalım.")]
        scen["new_conversation_again"] = [
            await bench.turn(None, "Merhaba, bugün plan yapalım.") for _ in range(reps)
        ]

        # 2. Histories of 2K–12K tokens. "fresh" = content the runtime has never seen (a new
        #    conversation per repetition); "restored" = seen before, then displaced from the
        #    runtime slot by another request (llama.cpp may restore it from its RAM cache).
        for size in SIZES:
            fresh, restored, pre_wait, pre_2s, pre_10s, warm = [], [], [], [], [], []
            for i in range(reps):
                cid = await bench.seed(size, rng)
                fresh.append(await bench.turn(cid, SHORT_TURNS[i % len(SHORT_TURNS)]))
                await bench.evict()
                restored.append(await bench.turn(cid, SHORT_TURNS[(i + 1) % len(SHORT_TURNS)]))
            for i in range(reps):
                cid = await bench.seed(size, rng)
                pre = await bench.prepare_and_wait(cid)
                pre_wait.append({**await bench.turn(cid, SHORT_TURNS[(i + 2) % len(SHORT_TURNS)]), **pre})
            for delay, bucket in ((2.0, pre_2s), (10.0, pre_10s)):
                for i in range(reps):
                    cid = await bench.seed(size, rng)
                    await engine.prepare(cid, model)  # what the UI does when a chat is opened
                    await asyncio.sleep(delay)  # the user sends after `delay` seconds
                    bucket.append({**await bench.turn(cid, SHORT_TURNS[(i + 3) % len(SHORT_TURNS)]), "send_after_s": delay})
            for i in range(reps + 2):
                warm.append(await bench.turn(cid, SHORT_TURNS[(i + 4) % len(SHORT_TURNS)]))
            scen[f"history_{size}"] = {
                "fresh_cold": fresh,
                "restored_after_displacement": restored,
                "prewarmed_then_sent": pre_wait,
                "opened_and_sent_after_2s": pre_2s,
                "opened_and_sent_after_10s": pre_10s,
                "warm": warm,
            }
            sample(f"after history_{size}")
            print(size, {k: [r["ttft_s"] for r in v] for k, v in scen[f"history_{size}"].items()}, flush=True)

        # 2b. An imported-like 12K conversation without runtime counts (conservative estimate).
        imported = await bench.seed(12000, rng, counted=False)
        scen["imported_12k_without_counts"] = [await bench.turn(imported, SHORT_TURNS[0])]

        # 3. First message after an app restart (new engine on the same database). The runtime
        #    keeps running, so its cache survives an app restart; after a model unload it does not.
        target = await bench.seed(8000, rng)
        await bench.turn(target, "Kısa bir not: yarın erken kalkacağım.")
        await bench.close()
        engine = await bench.open()
        restart_runtime_kept = await bench.turn(target, "Yarın için başka ne önerirsin?")
        await bench.close()
        await bench.llm.unload(model)
        await asyncio.sleep(2)
        engine = await bench.open()
        restart_cold = await bench.turn(target, "Bir de akşam için öneri?")
        await bench.close()
        await bench.llm.unload(model)
        await asyncio.sleep(2)
        engine = await bench.open()
        pre = await bench.prepare_and_wait(target)  # the UI pre-warms the reopened chat
        restart_prewarmed = {**await bench.turn(target, "Peki hafta sonu?"), **pre}
        scen["app_restart_8k"] = {
            "runtime_kept_running": restart_runtime_kept,
            "runtime_restarted_no_prewarm": restart_cold,
            "runtime_restarted_prewarmed": restart_prewarmed,
        }

        # 4. Model reload (keep_alive expired): the runner restarts and its caches are empty.
        await bench.llm.unload(model)
        engine.scheduler.cache = None
        await asyncio.sleep(2)
        reload_plain = await bench.turn(target, "Bugün neler yapmalıyım?")
        await bench.llm.unload(model)
        engine.scheduler.cache = None
        await asyncio.sleep(2)
        await engine.prepare(target, model)
        await asyncio.sleep(10.0)
        reload_10s = {**await bench.turn(target, "Bunu nasıl planlayalım?"), "send_after_s": 10.0}
        scen["model_reload_8k"] = {"no_prewarm": reload_plain, "prewarm_on_focus_sent_after_10s": reload_10s}

        # 5. Switching between two 8K conversations that were both used before.
        other = await bench.seed(8000, rng)
        await bench.turn(other, "B sohbetinde bir soru.")
        await bench.turn(target, "A sohbetine döndüm.")
        switch_restored = await bench.turn(other, "B sohbetine geçtim, ne konuşuyorduk?")
        await bench.turn(target, "Yine A.")
        pre = await bench.prepare_and_wait(other)
        switch_prewarmed = {**await bench.turn(other, "B sohbetinde devam edelim."), **pre}
        scen["switch_between_8k_conversations"] = {
            "no_prewarm": switch_restored,
            "prewarmed": switch_prewarmed,
        }
        sample("after switching")
        await bench.close()

        # 6. First message after compaction of a 12K conversation.
        for prewarm in (True, False):
            b2 = Bench(model, root / f"compact-{prewarm}", compact_at=6144, prewarm=prewarm, idle_delay=0.0)
            e2 = await b2.open()
            cid = await b2.seed(12000, rng)
            # A turn on the long conversation (under the hard limit, over compact_at): the user
            # then goes idle and the engine compacts in the background.
            trigger = await b2.turn(cid, "Kısa bir not daha ekleyeyim: cuma günü izinliyim.")
            before = await e2.context_info(cid)
            t0 = time.perf_counter()
            for _ in range(1200):
                await asyncio.sleep(0.25)
                info = await e2.context_info(cid)
                job = e2.scheduler.background
                if info["strategy"] == "summary_window" and job is None:
                    break
            compaction_s = round(time.perf_counter() - t0, 1)
            after = await e2.context_info(cid)
            first = await b2.turn(cid, "Kaldığımız yerden devam edelim; en son ne konuşuyorduk?")
            scen[f"after_compaction_12k_prewarm_{'on' if prewarm else 'off'}"] = {
                "trigger_turn": trigger,
                "tokens_before": before["estimated_tokens"],
                "tokens_after": after["estimated_tokens"],
                "summary": after["summary"],
                "compaction_and_prewarm_s": compaction_s,
                "first_turn": first,
            }
            await b2.close()
        sample("end")
        report["resident_gb_end"] = await bench.loaded_size_gb()
        report["loaded_models_end"] = [m.name for m in await bench.llm.loaded_models()]
        report["runner_peak_gb"] = max((m["runner_gb"] or 0) for m in memory)
        await bench.llm.aclose()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    report["summary"] = summarize_report(report)
    return report


def _ttfts(rows: list[dict[str, Any]]) -> dict[str, Any]:
    vals = [r["ttft_s"] for r in rows if r.get("ttft_s") is not None]
    ctx = [r["prompt_tokens"] for r in rows if r.get("prompt_tokens")]
    return {**summarize(vals), "prompt_tokens": summarize(ctx)}


def summarize_report(report: dict[str, Any]) -> dict[str, Any]:
    s = report["scenarios"]
    out: dict[str, Any] = {
        "new_conversation_first_ever": _ttfts(s["new_conversation_first_ever"]),
        "new_conversation_again": _ttfts(s["new_conversation_again"]),
    }
    errors: list[float] = []
    for size in SIZES:
        h = s[f"history_{size}"]
        out[f"history_{size}"] = {k: _ttfts(v) for k, v in h.items()}
        out[f"history_{size}"]["prewarm_s"] = summarize([r["prewarm_s"] for r in h["prewarmed_then_sent"]])
        for rows in h.values():
            for row in rows:
                if row.get("prompt_tokens") and row.get("estimated_tokens"):
                    errors.append((row["estimated_tokens"] - row["prompt_tokens"]) / row["prompt_tokens"])
    out["estimate_error_ratio"] = summarize(errors)  # > 0: conservative (overestimate)
    out["runner_peak_gb"] = report.get("runner_peak_gb")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--label", default="default", help="report name suffix, e.g. cache_ram_2048")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run(args.model, args.reps, args.label))
    path = OUT / f"conversation_perf_{args.label}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
