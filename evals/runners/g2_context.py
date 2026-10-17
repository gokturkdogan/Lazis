"""G2 (revised scope): short user turns (≤ 100 tokens) on growing conversation histories.

    uv run --project core python evals/runners/g2_context.py --model gemma4:12b-it-qat

For each history size the runner builds a fresh synthetic multi-turn history (random content, so
the runtime's prefix cache cannot help), sends one short user turn (cache miss: the whole history
is prefilled) and then five more short turns on the same conversation (cache warm: only the new
tokens are prefilled). Every turn records TTFT and the total input context the model received
(`prompt_eval_count`, which in Ollama 0.40 includes cached tokens). The new-token count per turn
is the difference to the previous turn's context plus its output; it bounds the user message
from above (it also contains the chat-template tokens).

Adds "g2_context" (or "g2_context_out<N>" with --max-output N) to the model's perf.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from typing import Any

from common import REPORTS, manifest, slug, summarize
from perf import BENCH_CTX, filler, options, run

from lazis.api.chat import PHASE2_SYSTEM_PROMPT
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import ChatMessage

HISTORY_TOKENS = (2000, 4000, 8000, 12000)
BUILDS_PER_SIZE = 2
WARM_TURNS = 5
MAX_OUTPUT = 64
SHORT_TURNS = [
    "Peki bunu kısaca özetler misin?",
    "Bugün akşam için ne önerirsin?",
    "Bunu yarın sabah yapsam olur mu?",
    "Sence en önemli nokta hangisiydi?",
    "Tamam, teşekkür ederim. Bir de kısa bir hatırlatma notu yazar mısın?",
    "Hafta sonu için de benzer bir plan yapabilir miyiz?",
]
G2_P50_MS, G2_P95_MS = 1200, 2500


def history(tokens: int, rng: random.Random) -> list[ChatMessage]:
    """System prompt plus alternating user (≈ 400 tokens) / assistant (≈ 150 tokens) turns."""
    msgs = [ChatMessage("system", PHASE2_SYSTEM_PROMPT)]
    used = 0
    while used < tokens:
        user = min(400, tokens - used)
        msgs.append(ChatMessage("user", f"Not {rng.randrange(10**6)}: " + filler(user, rng)))
        msgs.append(ChatMessage("assistant", "Anladım. " + filler(150, rng)))
        used += user + 150
    return msgs


async def measure(model: str, sizes_tokens: tuple[int, ...], max_output: int) -> dict[str, Any]:
    p = OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200)
    await p.load(model, num_ctx=BENCH_CTX, keep_alive="10m")
    rng = random.Random(20261017)
    sizes: list[dict[str, Any]] = []
    for size in sizes_tokens:
        cold: list[dict[str, Any]] = []
        warm: list[dict[str, Any]] = []
        for _ in range(BUILDS_PER_SIZE):
            msgs = history(size, rng)
            turns = rng.sample(SHORT_TURNS, k=WARM_TURNS + 1)
            prev_ctx = prev_out = None
            for i, text in enumerate(turns):
                msgs.append(ChatMessage("user", text))
                reply, m = await run(p, model, msgs, options(BENCH_CTX, max_output))
                msgs.append(ChatMessage("assistant", reply))
                row = {
                    "ttft_ms": round(m.ttft_ms, 1),
                    "total_input_tokens": m.prompt_tokens,
                    "user_chars": len(text),
                    "new_tokens": None if prev_ctx is None else m.prompt_tokens - prev_ctx - prev_out,
                }
                (cold if i == 0 else warm).append(row)
                prev_ctx, prev_out = m.prompt_tokens, m.output_tokens
        warm_ttft = summarize([r["ttft_ms"] for r in warm])
        sizes.append({
            "history_tokens_target": size,
            "total_input_tokens": summarize([r["total_input_tokens"] for r in cold + warm]),
            "new_tokens_per_warm_turn": summarize([r["new_tokens"] for r in warm]),
            "warm_ttft_ms": warm_ttft,
            "cold_ttft_ms": summarize([r["ttft_ms"] for r in cold]),
            "g2_warm_pass": bool(warm_ttft["median"] is not None and warm_ttft["p95"] is not None
                                 and warm_ttft["median"] <= G2_P50_MS and warm_ttft["p95"] <= G2_P95_MS),
            "turns": {"cold": cold, "warm": warm},
        })
        print(model, size, "warm", warm_ttft, "cold", sizes[-1]["cold_ttft_ms"]["median"], flush=True)
    await p.aclose()
    return {
        "description": "short user turns on synthetic multi-turn histories; cold = first turn on a "
                       f"fresh history (prefix-cache miss), warm = 5 following turns; num_ctx 16384; "
                       f"replies capped at {max_output} tokens",
        "gate": {"p50_ms": G2_P50_MS, "p95_ms": G2_P95_MS, "scope": "user turn <= 100 tokens, warm cache"},
        "max_output_tokens": max_output,
        "manifest": manifest(model),
        "sizes": sizes,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--max-output", type=int, default=MAX_OUTPUT, help="reply length cap (tokens)")
    ap.add_argument("--sizes", type=int, nargs="+", default=list(HISTORY_TOKENS))
    args = ap.parse_args()
    key = "g2_context" if args.max_output == MAX_OUTPUT else f"g2_context_out{args.max_output}"
    path = REPORTS / slug(args.model) / "perf.json"
    report = json.loads(path.read_text())
    report[key] = asyncio.run(measure(args.model, tuple(args.sizes), args.max_output))
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    main()
