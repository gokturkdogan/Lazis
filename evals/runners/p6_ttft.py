"""Phase 6: what memory costs the chat on the real runtime (production engine, synthetic data).

    uv run --project core python evals/runners/p6_ttft.py --model gemma4:12b-it-qat

The same 8-message conversation runs on two throwaway profiles:

* ``memory``: learning on, recall on, 1,000 synthetic records plus the facts the
  conversation itself states;
* ``baseline``: learning off, recall budget 0 (Phase 5 behaviour).

…each in two rhythms:

* ``patient``: the next message is sent after background work (re-warm, learning) is done —
  a user who reads the reply;
* ``fast``: the next message is sent 2 s after the reply — it preempts learning.

Per turn: TTFT as the user sees it (accepted → first token), runtime TTFT, prompt tokens,
recall time and items, and the learning job's duration. Writes
evals/reports/phase6/ttft_<model>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import secrets
import shutil
import statistics
import tempfile
import time
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
from lazis.memory import repository as memory_repo
from lazis.memory import service
from lazis.memory.service import Source
from lazis.providers.llm.ollama import OllamaProvider
from lazis.security.secrets import SecretBytes
from lazis.storage import open_storage

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase6"
MESSAGES = [
    "Merhaba, bugün biraz plan yapmak istiyorum.",
    "Ben İzmir'de yaşıyorum ve yazılım geliştiriciyim.",
    "Hafta sonu için kısa bir gezi önerir misin?",
    "Kuzenim Can da öğretmen, onunla gitmeyi düşünüyorum.",
    "Can'a küçük bir hediye almak istesem ne önerirsin?",
    "Bilgisayarımda 24 GB RAM var, yerel model için yeter mi?",
    "Peki bugün akşam için kısa bir çalışma planı yapalım.",
    "Teşekkürler, şimdilik bu kadar.",
]


async def conversation(
    model: str, *, memory: bool, rhythm: str, extract: bool | None = None, recall: bool | None = None
) -> list[dict[str, Any]]:
    extract = memory if extract is None else extract
    recall = memory if recall is None else recall
    root = Path(tempfile.mkdtemp(prefix="lazis-p6ttft-"))
    settings = Settings(
        app=AppSection(environment="test"),
        storage=StorageSection(data_dir=root / "data"),
        logging=LoggingSection(directory=root / "logs"),
        models=ModelsSection(max_output_tokens=200),
        conversation=ConversationSection(idle_compaction_delay_s=3600.0),
        memory=MemorySection(auto_extract=extract, context_budget_tokens=400 if recall else 0),
    )
    storage = open_storage(settings.storage, SecretBytes(secrets.token_bytes(32)), app_version="eval")
    llm = OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200)
    engine = ConversationEngine(db=storage.db, get_llm=lambda: llm, settings=settings)
    rows: list[dict[str, Any]] = []
    try:
        if recall:
            cands = synthetic(1000, random.Random(7))
            for i in range(0, len(cands), 200):
                storage.db.run_sync(lambda c, b=cands[i : i + 200]: service.apply_candidates(
                    c, b, source=Source("import"), explicit=True, actor="import", kind="import"))  # fmt: skip
        await engine.ensure_started()
        session = await engine.start_new_session(model)
        await engine.prepare(session.id, model)  # as the app does when the window opens
        await asyncio.sleep(0.5)
        while engine.scheduler.background is not None:
            await asyncio.sleep(0.2)
        cid: str | None = session.id
        for i, text in enumerate(MESSAGES):
            handle = await engine.begin_turn(TurnRequest(cid, f"ttft-{secrets.token_hex(6)}", text, model))
            events = [e async for e in engine.events(handle)]
            cid = handle.conversation.id
            last = dict(engine.last_turn or {})
            cache = next((e.get("cache") for e in events if e.get("stage") == "processing_context"), None)
            rows.append({
                "turn": i + 1, "ttft_ms": last.get("ttft_ms"), "runtime_ttft_ms": last.get("runtime_ttft_ms"),
                "prompt_tokens": last.get("prompt_tokens"), "cache": cache,
                "memory_items": last.get("memory_items"), "memory_ms": last.get("memory_ms"),
                "memory_request": last.get("memory_request"), "memory_request_ms": last.get("memory_request_ms"),
            })  # fmt: skip
            if rhythm == "fast":
                await asyncio.sleep(2.0)
            else:
                t0 = time.monotonic()
                await asyncio.sleep(0.5)
                while engine.scheduler.background is not None or engine._pending:  # pyright: ignore[reportPrivateUsage]
                    if time.monotonic() - t0 > 120:
                        break
                    await asyncio.sleep(0.2)
                rows[-1]["background_ms"] = round((time.monotonic() - t0) * 1000)
            rows[-1]["learning"] = {k: engine.learner.status.get(k) for k in ("state", "duration_ms", "prompt_tokens", "output_tokens", "on_prefix")}
        rows.append({"jobs": storage.db.run_sync(memory_repo.job_counts)})
    finally:
        await engine.close()
        await llm.aclose()
        storage.db.close()
        shutil.rmtree(root, ignore_errors=True)
    return rows


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    turns = [r for r in rows if "turn" in r and r["turn"] > 1]  # turn 1 = first contact
    ttft = [r["ttft_ms"] for r in turns if r["ttft_ms"] is not None]
    return {
        "ttft_ms_median": round(statistics.median(ttft)) if ttft else None,
        "ttft_ms_max": round(max(ttft)) if ttft else None,
        "warm_turns": sum(1 for r in turns if r["cache"] == "warm"),
        "turns": len(turns),
    }


VARIANTS = {
    "baseline": {"memory": False},
    "memory": {"memory": True},
    "extract_only": {"memory": False, "extract": True, "recall": False},
    "recall_only": {"memory": False, "extract": False, "recall": True},
}


async def run(model: str, rhythms: list[str], variants: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for rhythm in rhythms:
        for variant in variants:
            key = f"{rhythm}_{variant}"
            rows = await conversation(model, rhythm=rhythm, **VARIANTS[variant])  # type: ignore[arg-type]
            out[key] = {"summary": summarise(rows), "turns": rows}
            print(key, json.dumps(out[key]["summary"]), flush=True)
    return {"model": model, "manifest": manifest(model), "runs": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--rhythms", default="patient,fast")
    ap.add_argument("--variants", default="baseline,memory")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    report = asyncio.run(run(args.model, args.rhythms.split(","), args.variants.split(",")))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"ttft_{re.sub(r'[:/]', '_', args.model)}{'_' + args.label if args.label else ''}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(path)


if __name__ == "__main__":
    main()
