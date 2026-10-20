"""Phase 7: what the relationship graph costs the chat on the real runtime (synthetic data).

    uv run --project core python evals/runners/p7_ttft.py --model gemma4:12b-it-qat

The same 8-message conversation (relationship statements and questions mixed with ordinary
messages) runs on throwaway profiles:

* ``baseline``: learning off, recall budget 0 (Phase 5 behaviour);
* ``memory``: learning and recall on, 1,000 synthetic records (Phase 6 conditions);
* ``graph``: as ``memory`` plus a synthetic graph of 5,000 relationships (evals/runners/
  p7_perf.py's generator) — relationship questions are answered from it.

Rhythm ``patient``: the next message is sent after background work is done. Per turn: TTFT as
the user sees it (accepted → first token), runtime TTFT, prompt tokens, recall time and
items, the request path. Writes evals/reports/phase7/ttft_<model>.json.
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
from p7_perf import seed as seed_graph

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
from lazis.memory import service
from lazis.memory.service import Source
from lazis.providers.llm.ollama import OllamaProvider
from lazis.security.secrets import SecretBytes
from lazis.storage import open_storage

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase7"
MESSAGES = [
    "Merhaba, bugün biraz plan yapmak istiyorum.",
    "Çocukluk arkadaşım Ahmet Yılmaz bu akşam bize gelecek.",
    "Hafta sonu için kısa bir gezi önerir misin?",
    "Çocukluk arkadaşım Ahmet Yılmaz'ın kardeşi kim?",
    "Çocukluk arkadaşım Ahmet Yılmaz'ın kardeşinin eşi kim?",
    "Can Kaya'yı nereden tanıyorum?",
    "Bilgisayarımda 24 GB RAM var, yerel model için yeter mi?",
    "Teşekkürler, şimdilik bu kadar.",
]


async def conversation(model: str, variant: str) -> list[dict[str, Any]]:
    memory = variant != "baseline"
    root = Path(tempfile.mkdtemp(prefix="lazis-p7ttft-"))
    settings = Settings(
        app=AppSection(environment="test"),
        storage=StorageSection(data_dir=root / "data"),
        logging=LoggingSection(directory=root / "logs"),
        models=ModelsSection(max_output_tokens=200),
        conversation=ConversationSection(idle_compaction_delay_s=3600.0),
        memory=MemorySection(auto_extract=memory, context_budget_tokens=400 if memory else 0),
    )
    storage = open_storage(settings.storage, SecretBytes(secrets.token_bytes(32)), app_version="eval")
    llm = OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200)
    engine = ConversationEngine(db=storage.db, get_llm=lambda: llm, settings=settings)
    rows: list[dict[str, Any]] = []
    try:
        if memory:
            cands = synthetic(1000, random.Random(7))
            for i in range(0, len(cands), 200):
                storage.db.run_sync(lambda c, b=cands[i : i + 200]: service.apply_candidates(
                    c, b, source=Source("import"), explicit=True, actor="import", kind="import"))  # fmt: skip
        if variant == "graph":
            seed_graph(storage.db, 5000, random.Random(5000))
        await engine.ensure_started()
        session = await engine.start_new_session(model)
        await engine.prepare(session.id, model)
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
            reply = next((e["message"]["content"] for e in events if e["type"] == "done"), None)
            rows.append({
                "turn": i + 1, "user": text, "reply": reply, "ttft_ms": last.get("ttft_ms"),
                "runtime_ttft_ms": last.get("runtime_ttft_ms"), "prompt_tokens": last.get("prompt_tokens"),
                "cache": cache, "memory_items": last.get("memory_items"), "memory_ms": last.get("memory_ms"),
                "memory_request": last.get("memory_request"),
            })  # fmt: skip
            t0 = time.monotonic()
            await asyncio.sleep(0.5)
            while engine.scheduler.background is not None or engine._pending:  # pyright: ignore[reportPrivateUsage]
                if time.monotonic() - t0 > 120:
                    break
                await asyncio.sleep(0.2)
            rows[-1]["background_ms"] = round((time.monotonic() - t0) * 1000)
    finally:
        await engine.close()
        await llm.aclose()
        storage.db.close()
        shutil.rmtree(root, ignore_errors=True)
    return rows


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    turns = [r for r in rows if r["turn"] > 1]
    ttft = [r["ttft_ms"] for r in turns if r["ttft_ms"] is not None]
    mem = [r["memory_ms"] for r in turns if r["memory_ms"] is not None]
    return {
        "ttft_ms_median": round(statistics.median(ttft)) if ttft else None,
        "ttft_ms_max": round(max(ttft)) if ttft else None,
        "recall_ms_max": max(mem) if mem else None,
        "warm_turns": sum(1 for r in turns if r["cache"] == "warm"),
        "turns": len(turns),
    }


async def run(model: str, variants: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for variant in variants:
        rows = await conversation(model, variant)
        out[variant] = {"summary": summarise(rows), "turns": rows}
        print(variant, json.dumps(out[variant]["summary"]), flush=True)
    return {"model": model, "manifest": manifest(model), "runs": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--variants", default="baseline,memory,graph")
    args = ap.parse_args()
    report = asyncio.run(run(args.model, args.variants.split(",")))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"ttft_{re.sub(r'[:/]', '_', args.model)}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(path)


if __name__ == "__main__":
    main()
