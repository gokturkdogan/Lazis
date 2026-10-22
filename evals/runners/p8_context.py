"""Phase 8, condition E with the real model: after an import, a person whose identity is not
settled is never answered about (synthetic data only).

    uv run --project core python evals/runners/p8_context.py --model gemma4:12b-it-qat

One throwaway encrypted profile; a JSON profile is imported and applied (two Ahmets: the
neighbour, whose sibling is Elif and who is an architect; the colleague, whose sibling is
Zeynep and who is an accountant). Then each question runs in a new session through the
production engine. A bare "Ahmet" must get a "which one?" question and neither Ahmet's
details; relation words settle which one. Per turn: the reply, the claim state, unbacked
memory claims, internal labels. Replies are also read by hand. Writes
evals/reports/phase8/context_<model>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any

from common import manifest
from p6_sessions import Profile
from p71_claims import ClaimRecorder, Turn, say, unbacked
from p72_identity import LABELS

from lazis.bootstrap import apply, files, pipeline, store
from lazis.memory import text
from lazis.providers.llm.ollama import OllamaProvider

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase8"
DOC = {
    "schema_version": "1.0",
    "profile": {"name": "Kerem", "occupation": "veri analisti"},
    "people": [
        {"id": "ak", "name": "Ahmet", "relation": "komşum", "facts": {"occupation": "mimar"}},
        {"id": "ai", "name": "Ahmet", "relation": "iş arkadaşım", "facts": {"occupation": "muhasebeci"}},
        {"id": "e", "name": "Elif", "facts": {"occupation": "pilot"}},
        {"id": "z", "name": "Zeynep", "facts": {"occupation": "avukat"}},
    ],
    "relationships": [{"from": "ak", "type": "sibling", "to": "e"}, {"from": "ai", "type": "sibling", "to": "z"}],
}
ASKS = re.compile(r"hangi|hangisi|komşunuz.*iş arkadaşınız|iş arkadaşınız.*komşunuz|kimden bahsediyorsunuz", re.I)
# id, question, must contain (any), must not contain (any), must ask which one
QUESTIONS: list[tuple[str, str, list[str], list[str], bool]] = [
    ("e01", "Ahmet'in kardeşi kim?", [], ["Elif", "Zeynep"], True),
    ("e02", "Ahmet ne iş yapıyor?", [], ["mimar", "muhasebeci"], True),
    ("e03", "Ahmet hakkında ne biliyorsun?", [], ["mimar", "muhasebeci", "Elif", "Zeynep"], True),
    ("e04", "Komşum Ahmet'in kardeşi kim?", ["Elif"], ["Zeynep"], False),
    ("e05", "İş arkadaşım Ahmet ne iş yapıyor?", ["muhasebeci"], ["mimar"], False),
    ("e06", "Komşum Ahmet'in mesleği ne?", ["mimar"], ["muhasebeci"], False),
    ("e07", "Ahmet'e doğum günü için ne alsam?", [], ["mimar", "muhasebeci", "Elif", "Zeynep"], True),
    ("e08", "Elif ne iş yapıyor?", ["pilot"], [], False),
]


def contains(reply: str, word: str) -> bool:
    return text.fold(word) in text.fold(reply)


async def run(model: str) -> dict[str, Any]:
    llm = ClaimRecorder(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200))
    p = Profile(model, llm)
    await p.start()
    out: list[dict[str, Any]] = []
    try:
        f = files.read("profil.json", json.dumps(DOC, ensure_ascii=False).encode())
        iid = p.q(lambda c: pipeline.start_json(c, f))

        def decide(c: Any) -> None:
            for x in store.people(c, iid):
                store.decide_person(c, iid, x.id, "create")
            for it in store.items(c, iid):
                store.decide_item(c, iid, it.id, "approve")

        p.q(decide)
        counts = p.q(lambda c: apply.apply(c, iid)).counts
        for qid, question, must, never, ask in QUESTIONS:
            await p.clean_session()
            r = await say(p, llm, Turn(question))
            reply = r["reply"] or ""
            checks = {
                "has_expected": all(contains(reply, w) for w in must),
                "no_other_persons_details": not any(contains(reply, w) for w in never),
                "asks_which_one": bool(ASKS.search(reply)) if ask else True,
                "no_shown_claim": not r["final_unbacked"] and not r["intermediate_only"],
                "shown_equals_stored": r["same_text"],
                "no_internal_label": not LABELS.findall(reply),
            }
            ok = all(checks.values())
            print(f"[{'ok ' if ok else 'FAIL'}] {qid} {question} {checks}\n      L: {reply[:400]!r}", flush=True)
            out.append({"id": qid, "question": question, "reply": reply, "checks": checks, "passed": ok,
                        "claim_state": r["claim_state"], "raw_unbacked": bool(unbacked(r["raw"], r["claim_state"]))})
    finally:
        await p.stop()
        p.remove()
        await llm.inner.aclose()
    return {"model": model, "manifest": manifest(model), "import_counts": counts,
            "summary": {"questions": len(out), "passed": sum(x["passed"] for x in out),
                        "leaked_other_person": sum(not x["checks"]["no_other_persons_details"] for x in out),
                        "did_not_ask": sum(not x["checks"]["asks_which_one"] for x in out)},
            "turns": out}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:12b-it-qat")
    args = ap.parse_args()
    report = asyncio.run(run(args.model))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"context_{re.sub(r'[:/]', '_', args.model)}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False), path)


if __name__ == "__main__":
    main()
