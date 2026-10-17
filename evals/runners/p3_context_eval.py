"""Phase 3 context accuracy: does LAZIS still answer correctly after compaction?

    uv run --project core python evals/runners/p3_context_eval.py --model gemma4:12b-it-qat

For every dialogue in datasets/tr_compaction_v1.json (synthetic, fictional people):

* ``full``      — the whole history is sent verbatim, then the probes are asked;
* ``compacted`` — the production compactor summarizes everything but a short verbatim tail
                  (the key facts are all in the summarized part), then the same probes.

Scores: probe accuracy (normalized expect_any / expect_all / forbid), summary fact recall
(summary_expect strings in the rendered summary), items kept / dropped by the evidence check,
and compaction time. Uses a throwaway encrypted database (random in-memory key) that is
deleted afterwards. Writes evals/reports/phase3/context_eval.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from common import REPO, manifest

from lazis.config.model import (
    AppSection,
    ConversationSection,
    LoggingSection,
    ModelsSection,
    Settings,
    StorageSection,
)
from lazis.conversation import ConversationEngine, TurnRequest, repository
from lazis.conversation.compaction import normalize
from lazis.ids import utc_now_iso
from lazis.providers.llm.ollama import OllamaProvider
from lazis.security.secrets import SecretBytes
from lazis.storage import open_storage

DATA = REPO / "evals" / "datasets" / "tr_compaction_v1.json"
OUT = REPO / "evals" / "reports" / "phase3"
NOTE = "[Mesaj zamanı: 17 Ekim 2026 Cumartesi 14:32]"


def score(answer: str, probe: dict[str, Any]) -> dict[str, Any]:
    text = normalize(answer)
    any_ok = not probe.get("expect_any") or any(normalize(x) in text for x in probe["expect_any"])
    all_ok = all(normalize(x) in text for x in probe.get("expect_all", []))
    forbidden = [x for x in probe.get("forbid", []) if normalize(x) in text]
    return {"pass": any_ok and all_ok and not forbidden, "any_ok": any_ok, "all_ok": all_ok, "forbidden": forbidden}


async def run(model: str) -> dict[str, Any]:
    dataset = json.loads(DATA.read_text())
    root = Path(tempfile.mkdtemp(prefix="lazis-p3-ctx-"))
    settings = Settings(
        app=AppSection(environment="test"),
        storage=StorageSection(data_dir=root / "data"),
        logging=LoggingSection(directory=root / "logs"),
        models=ModelsSection(max_output_tokens=200),
        conversation=ConversationSection(
            keep_recent_tokens=256, keep_recent_messages=4, idle_compaction_delay_s=3600.0
        ),
    )
    llm = OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200)
    storage = open_storage(settings.storage, SecretBytes(secrets.token_bytes(32)), app_version="eval")
    engine = ConversationEngine(db=storage.db, get_llm=lambda: llm, settings=settings)
    results: list[dict[str, Any]] = []
    counter = 0
    try:
        await engine.ensure_started()
        for dialogue in dataset["dialogues"]:
            for mode in ("full", "compacted"):
                now = utc_now_iso()

                def seed(conn: repository.Connection, d: dict[str, Any] = dialogue) -> str:
                    with repository.transaction(conn):
                        conv = repository.insert_conversation(conn, title=d["id"], model=model, now=now)
                        for role, content in d["messages"]:
                            repository.insert_message(
                                conn,
                                conversation_id=conv.id,
                                role=role,
                                content=content,
                                status="complete",
                                now=now,
                                context_note=NOTE if role == "user" else None,
                            )
                        return conv.id

                cid = storage.db.run_sync(seed)
                row: dict[str, Any] = {"dialogue": dialogue["id"], "mode": mode}
                if mode == "compacted":
                    t0 = time.perf_counter()
                    done = await engine.compact_now(cid)
                    row["compaction_s"] = round(time.perf_counter() - t0, 1)
                    summaries = storage.db.run_sync(lambda c, i=cid: repository.list_summaries(c, i))
                    active = next((s for s in summaries if s.status == "active"), None)
                    row["compacted"] = done and active is not None
                    if active is not None:
                        rendered = normalize(active.rendered)
                        # Only facts whose source message was actually summarized count.
                        expect = [x for x, seq in dialogue["summary_expect"] if seq <= active.to_seq]
                        hits = [x for x in expect if normalize(x) in rendered]
                        row["summary"] = {
                            "to_seq": active.to_seq,
                            "kept_items": active.kept_items,
                            "dropped_items": active.dropped_items,
                            "facts_in_range": len(expect),
                            "fact_recall": round(len(hits) / len(expect), 3) if expect else None,
                            "missing": [x for x in expect if x not in hits],
                            "rendered": active.rendered,
                        }
                probes = []
                for probe in dialogue["probes"]:
                    counter += 1
                    handle = await engine.begin_turn(
                        TurnRequest(cid, f"eval-{counter:05d}-{secrets.token_hex(3)}", probe["q"], model)
                    )
                    answer = ""
                    async for event in engine.events(handle):
                        if event["type"] == "delta":
                            answer += str(event["text"])
                    probes.append({"q": probe["q"], "answer": answer, **score(answer, probe)})
                row["probes"] = probes
                row["accuracy"] = round(sum(p["pass"] for p in probes) / len(probes), 3)
                results.append(row)
                print(dialogue["id"], mode, row["accuracy"], row.get("summary", {}).get("fact_recall"), flush=True)
    finally:
        await engine.close()
        await llm.aclose()
        storage.db.close()
        shutil.rmtree(root, ignore_errors=True)

    def agg(mode: str) -> dict[str, Any]:
        rows = [r for r in results if r["mode"] == mode]
        probes = [p for r in rows for p in r["probes"]]
        out: dict[str, Any] = {
            "probe_accuracy": round(sum(p["pass"] for p in probes) / len(probes), 3),
            "probes": len(probes),
        }
        if mode == "compacted":
            sums = [r["summary"] for r in rows if "summary" in r]
            facts = sum(s["facts_in_range"] for s in sums)
            found = sum(s["facts_in_range"] - len(s["missing"]) for s in sums)
            out["summary_fact_recall"] = round(found / facts, 3) if facts else None
            out["facts_in_range"] = facts
            out["kept_items"] = sum(s["kept_items"] for s in sums)
            out["dropped_items"] = sum(s["dropped_items"] for s in sums)
            out["compaction_s"] = [r["compaction_s"] for r in rows]
        return out

    return {
        "manifest": manifest(model),
        "dataset_version": dataset["version"],
        "results": results,
        "summary": {"full": agg("full"), "compacted": agg("compacted")},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    report = asyncio.run(run(args.model))
    (OUT / "context_eval.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
