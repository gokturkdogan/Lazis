"""Phase 2 performance benchmarks (BENCHMARK_PLAN §4: B1, B2, B3, B4 + num_ctx and long context).

    uv run --project core python evals/runners/perf.py --model qwen3.5:9b-q4_K_M [--quick]

All prompts are synthetic Turkish text. Each latency scenario: 1 warm-up + N measured runs
(N=10, --quick: 3); median / p95 reported. A random nonce at the start of every prompt defeats
Ollama's prefix cache where a cold prefill is intended.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import time
from typing import Any

from common import (
    manifest,
    memory_state,
    footprint_mb,
    runner_commands,
    runner_pids,
    summarize,
    write_report,
)

from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import (
    ChatMessage,
    ChatRequest,
    GenerationDone,
    GenerationMetrics,
    GenerationOptions,
    TextDelta,
)

CTX_SWEEP = (4096, 8192, 16384, 32768)
BENCH_CTX = 16384
SIZES = (512, 2048, 8192)
CHARS_PER_TOKEN = 3.2  # rough Turkish estimate; actual counts come from prompt_eval_count

SUBJECTS = ["Kasabanın kütüphanesi", "Bahar şenliği", "Belediyenin yeni parkı", "Küçük fırın",
            "Liman yolundaki kafe", "Okulun bilim kulübü", "Dağ evindeki atölye", "Pazar yeri"]
VERBS = ["bu yıl yeniden düzenlendi", "ziyaretçilerden yoğun ilgi gördü", "akşam saatlerinde açık kaldı",
         "gönüllülerin desteğiyle büyüdü", "yeni bir etkinlik takvimi duyurdu", "yağmura rağmen kalabalıktı"]
DETAILS = ["çocuklar için masal saatleri düzenlendi", "yerel üreticiler ürünlerini tanıttı",
           "eski fotoğraflardan oluşan bir sergi açıldı", "akşamları küçük bir konser verildi",
           "bisiklet park alanı genişletildi", "kitap bağışı kampanyası başlatıldı"]


def filler(tokens: int, rng: random.Random) -> str:
    target = int(tokens * CHARS_PER_TOKEN)
    parts: list[str] = []
    size = 0
    while size < target:
        s = f"{rng.choice(SUBJECTS)} {rng.choice(VERBS)}; {rng.choice(DETAILS)}. "
        parts.append(s)
        size += len(s)
    return "".join(parts)


def options(num_ctx: int, max_tokens: int, **kw: Any) -> GenerationOptions:
    return GenerationOptions(num_ctx=num_ctx, max_tokens=max_tokens, seed=42, think=False, **kw)


async def run(p: OllamaProvider, model: str, messages: list[ChatMessage], opts: GenerationOptions) -> tuple[str, GenerationMetrics]:
    text: list[str] = []
    metrics: GenerationMetrics | None = None
    async for ev in p.stream(ChatRequest(model, messages, opts)):
        if isinstance(ev, TextDelta) and ev.kind == "content":
            text.append(ev.text)
        elif isinstance(ev, GenerationDone):
            metrics = ev.metrics
    assert metrics is not None
    return "".join(text), metrics


async def wait_unloaded(p: OllamaProvider, model: str) -> None:
    await p.unload(model)
    for _ in range(100):
        if not any(m.name == model for m in await p.loaded_models()):
            return
        await asyncio.sleep(0.1)


def runner_footprint() -> float | None:
    values = [f for f in (footprint_mb(pid) for pid in runner_pids()) if f is not None]
    return round(sum(values), 1) if values else None


async def bench(model: str, reps: int) -> dict[str, Any]:
    p = OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200)
    rng = random.Random(20261017)
    report: dict[str, Any] = {"manifest": manifest(model), "reps": reps}
    hello = [ChatMessage("user", "Merhaba")]

    # B1 — cold load (model unloaded, file cache warm)
    cold = []
    for _ in range(5):
        await wait_unloaded(p, model)
        t0 = time.monotonic()
        _, m = await run(p, model, hello, options(8192, 1))
        cold.append({"wall_ms": (time.monotonic() - t0) * 1000, "load_ms": m.load_ms, "ttft_ms": m.ttft_ms})
    report["b1_cold_load"] = {
        "wall_ms": summarize([c["wall_ms"] for c in cold]),
        "load_ms": summarize([c["load_ms"] for c in cold]),
        "runs": cold,
    }

    # num_ctx sweep: memory per context size and whether a change reloads the model
    sweep = []
    for ctx in CTX_SWEEP:
        await wait_unloaded(p, model)
        t0 = time.monotonic()
        await p.load(model, num_ctx=ctx, keep_alive="10m")
        load_ms = (time.monotonic() - t0) * 1000
        _, warm = await run(p, model, hello, options(ctx, 1))  # allocate the KV cache for real
        ps = next(m for m in await p.loaded_models() if m.name == model)
        sweep.append({
            "num_ctx": ctx,
            "load_ms": round(load_ms, 1),
            "ollama_size_gb": round(ps.size_bytes / 2**30, 2),
            "ollama_vram_gb": round(ps.vram_bytes / 2**30, 2),
            "reported_context": ps.context_length,
            "runner_footprint_mb": runner_footprint(),
            "runner": runner_commands(),
            "first_request_load_ms": warm.load_ms,
        })
    report["num_ctx_sweep"] = sweep
    await wait_unloaded(p, model)
    await p.load(model, num_ctx=8192)
    _, same = await run(p, model, hello, options(8192, 1))
    _, changed = await run(p, model, hello, options(16384, 1))
    _, back = await run(p, model, hello, options(8192, 1))
    report["num_ctx_reload"] = {
        "same_ctx_load_ms": same.load_ms,
        "changed_ctx_load_ms": changed.load_ms,
        "changed_back_load_ms": back.load_ms,
        "note": "load_ms well above ~0 means the runner was restarted for the new num_ctx",
    }

    # B2 — warm single-turn latency at BENCH_CTX, distinct prompts (no prefix reuse)
    await p.load(model, num_ctx=BENCH_CTX, keep_alive="30m")
    mem_before = memory_state()
    peak_fp = runner_footprint() or 0.0
    b2: dict[str, Any] = {}
    for size in SIZES:
        runs = []
        for i in range(reps + 1):
            nonce = f"[Oturum {rng.randrange(10**9)}] "
            msg = nonce + filler(size, rng) + "\n\nYukarıdaki metni 3 cümleyle özetle."
            _, m = await run(p, model, [ChatMessage("user", msg)], options(BENCH_CTX, 128))
            peak_fp = max(peak_fp, runner_footprint() or 0.0)
            if i > 0:  # first run is the warm-up
                runs.append({"prompt_tokens": m.prompt_tokens, "ttft_ms": m.ttft_ms, "prefill_tps": m.prefill_tps,
                             "decode_tps": m.decode_tps, "output_tokens": m.output_tokens, "total_ms": m.total_ms})
        b2[str(size)] = {
            "prompt_tokens": summarize([r["prompt_tokens"] for r in runs]),
            "ttft_ms": summarize([r["ttft_ms"] for r in runs]),
            "prefill_tps": summarize([r["prefill_tps"] for r in runs]),
            "decode_tps": summarize([r["decode_tps"] for r in runs]),
            "runs": runs,
        }
    report["b2_warm_latency"] = {"num_ctx": BENCH_CTX, "output_tokens_max": 128, "by_prompt_size": b2}

    # B3 — append-only multi-turn session: does the prefix cache work?
    history = [ChatMessage("system", "Sen yardımsever bir Türkçe asistansın. Kısa yanıt ver."),
               ChatMessage("user", "Sana bir kasabanın günlüğünü anlatacağım. " + filler(1800, rng))]
    turns = []
    for turn in range(10):
        reply, m = await run(p, model, history, options(BENCH_CTX, 120))
        turns.append({"turn": turn + 1, "prompt_eval_count": m.prompt_tokens, "prompt_ms": m.prompt_ms,
                      "ttft_ms": m.ttft_ms, "decode_tps": m.decode_tps})
        history = [*history, ChatMessage("assistant", reply),
                   ChatMessage("user", f"Devam ediyorum ({turn + 2}. gün): " + filler(rng.randint(300, 600), rng))]
    # replay each turn's prompt with a cache-busting nonce to learn its full token count
    replay_hist = [history[0], history[1]]
    full_counts = []
    for turn in range(10):
        busted = [ChatMessage("system", f"[{rng.randrange(10**9)}] " + replay_hist[0].content), *replay_hist[1:]]
        _, m = await run(p, model, busted, options(BENCH_CTX, 1))
        full_counts.append(m.prompt_tokens)
        idx = 2 + 2 * turn
        replay_hist = history[: idx + 2]
    # Ollama 0.40 counts cached tokens in prompt_eval_count, so reuse is estimated from time:
    # tokens actually computed ≈ prompt_eval_duration × cold prefill rate (B2, 2K prompts).
    cold_rate = b2["2048"]["prefill_tps"]["median"] or 0
    for t, full in zip(turns, full_counts, strict=True):
        t["full_prompt_tokens"] = full
        computed = (t["prompt_ms"] or 0) / 1000 * cold_rate
        t["est_computed_tokens"] = round(computed)
        t["est_reuse_ratio"] = round(max(0.0, 1 - computed / full), 3) if full else None
    report["b3_multiturn_cache"] = {
        "turns": turns,
        "cold_prefill_tps_used": cold_rate,
        "est_reuse_ratio_turns_2_10": summarize([t["est_reuse_ratio"] for t in turns[1:]]),
        "ttft_ms_turns_2_10": summarize([t["ttft_ms"] for t in turns[1:]]),
    }

    # Long context: three planted facts in a ~12K-token haystack at BENCH_CTX
    facts = [("Fenerin bekçisinin kedisinin adı Kehribar'dır.", "Fenerin bekçisinin kedisinin adı ne?", "kehribar"),
             ("Değirmenin anahtarı mavi kapılı evdeki çekmecede saklanıyor.", "Değirmenin anahtarı nerede saklanıyor?", "çekmece"),
             ("Şenliğin kapanış konseri saat 21:45'te başladı.", "Kapanış konseri saat kaçta başladı?", "21:45")]
    needles = []
    for pos, (fact, question, answer) in zip((0.1, 0.5, 0.9), facts, strict=True):
        hay = filler(12000, rng)
        cut = int(len(hay) * pos)
        text = f"[{rng.randrange(10**9)}] " + hay[:cut] + " " + fact + " " + hay[cut:]
        reply, m = await run(p, model, [ChatMessage("user", text + f"\n\nSoru: {question} Kısa yanıt ver.")],
                             options(BENCH_CTX, 40))
        needles.append({"position": pos, "prompt_tokens": m.prompt_tokens, "ttft_ms": m.ttft_ms,
                        "correct": answer in reply.lower(), "answer": reply.strip()[:120]})
    report["long_context"] = {"num_ctx": BENCH_CTX, "needles": needles,
                              "accuracy": sum(n["correct"] for n in needles) / len(needles)}

    report["b4_memory"] = {
        "before_b2": mem_before,
        "after_all": memory_state(),
        "runner_peak_footprint_mb": round(peak_fp, 1) if peak_fp else None,
        "loaded": [vars(m) for m in await p.loaded_models()],
    }
    report["finished_at_thermal"] = manifest(model)["thermal"]
    await p.aclose()
    return report


async def memory_only(model: str) -> dict[str, Any]:
    """Peak runner footprint while prefilling an 8K prompt at BENCH_CTX (sampled every 0.25 s)."""
    p = OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200)
    rng = random.Random(7)
    await p.load(model, num_ctx=BENCH_CTX, keep_alive="10m")
    idle = runner_footprint()
    samples: list[float] = []
    stop = asyncio.Event()

    async def sampler() -> None:
        while not stop.is_set():
            value = await asyncio.to_thread(runner_footprint)
            if value:
                samples.append(value)
            await asyncio.sleep(0.25)

    task = asyncio.create_task(sampler())
    for _ in range(2):
        msg = f"[{rng.randrange(10**9)}] " + filler(8192, rng) + "\n\nYukarıdaki metni özetle."
        await run(p, model, [ChatMessage("user", msg)], options(BENCH_CTX, 64))
    stop.set()
    await task
    ps = next(m for m in await p.loaded_models() if m.name == model)
    await p.aclose()
    return {"num_ctx": BENCH_CTX, "idle_footprint_mb": idle, "peak_footprint_mb": max(samples, default=None),
            "samples": len(samples), "ollama_size_gb": round(ps.size_bytes / 2**30, 2), "memory": memory_state()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--memory-only", action="store_true", help="add precise peak memory to perf.json")
    args = ap.parse_args()
    if args.memory_only:
        from common import REPORTS, slug
        import json
        path = REPORTS / slug(args.model) / "perf.json"
        report = json.loads(path.read_text())
        report["b4_memory"]["precise_peak"] = asyncio.run(memory_only(args.model))
        path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
        print(report["b4_memory"]["precise_peak"])
        return
    t0 = time.monotonic()
    report = asyncio.run(bench(args.model, 3 if args.quick else 10))
    report["duration_s"] = round(time.monotonic() - t0, 1)
    path = write_report(args.model, "perf", report)
    b2 = report["b2_warm_latency"]["by_prompt_size"]
    print(f"wrote {path} in {report['duration_s']} s")
    for size, d in b2.items():
        print(f"  {size:>5} tok: TTFT p50 {d['ttft_ms']['median']} ms, prefill {d['prefill_tps']['median']} t/s, decode {d['decode_tps']['median']} t/s")


if __name__ == "__main__":
    main()
