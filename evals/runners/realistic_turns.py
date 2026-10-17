"""Supplementary B3 variant: realistic short user turns (20–60 tokens) on a 2K-token history.

    uv run --project core python evals/runners/realistic_turns.py --model gemma4:12b-it-qat
Adds "b3_realistic_turns" to the model's perf.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random

from common import REPORTS, slug, summarize
from perf import BENCH_CTX, filler, options, run

from lazis.api.chat import PHASE2_SYSTEM_PROMPT
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import ChatMessage

TURNS = [
    "Bugün biraz yorgunum ama akşam yürüyüşe çıkmayı düşünüyorum.",
    "Sence kaç dakika yürümek yeterli olur?",
    "Peki yürüyüşten sonra hafif bir akşam yemeği için ne önerirsin?",
    "Evde yumurta, ıspanak ve biraz peynir var.",
    "Tamam, tarifini kısaca yazar mısın?",
    "Yarın sabah erken bir toplantım var, kaçta yatmalıyım?",
    "Saat 8'de toplantı, hazırlanmak için 1 saat lazım.",
    "Uyumadan önce telefonu bırakmak gerçekten fark eder mi?",
    "Teşekkürler, son olarak bana kısa bir iyi geceler mesajı yazar mısın?",
    "Bir de yarın için kısa bir yapılacaklar listesi önerir misin?",
]


async def measure(model: str) -> dict[str, object]:
    p = OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200)
    rng = random.Random(11)
    await p.load(model, num_ctx=BENCH_CTX, keep_alive="10m")
    history = [ChatMessage("system", PHASE2_SYSTEM_PROMPT),
               ChatMessage("user", "Önce sana kasabamızı anlatayım: " + filler(1800, rng)),]
    reply, _ = await run(p, model, history, options(BENCH_CTX, 150))
    history.append(ChatMessage("assistant", reply))
    turns = []
    for text in TURNS:
        history.append(ChatMessage("user", text))
        reply, m = await run(p, model, history, options(BENCH_CTX, 150))
        history.append(ChatMessage("assistant", reply))
        turns.append({"ttft_ms": m.ttft_ms, "prompt_tokens": m.prompt_tokens, "prompt_ms": m.prompt_ms,
                      "decode_tps": m.decode_tps})
    await p.aclose()
    return {"description": "2K-token history, 10 short user turns (20–60 tokens), num_ctx 16384",
            "ttft_ms": summarize([t["ttft_ms"] for t in turns]),
            "final_prompt_tokens": turns[-1]["prompt_tokens"], "turns": turns}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    args = ap.parse_args()
    path = REPORTS / slug(args.model) / "perf.json"
    report = json.loads(path.read_text())
    report["b3_realistic_turns"] = asyncio.run(measure(args.model))
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(args.model, report["b3_realistic_turns"]["ttft_ms"], "final prompt", report["b3_realistic_turns"]["final_prompt_tokens"])


if __name__ == "__main__":
    main()
