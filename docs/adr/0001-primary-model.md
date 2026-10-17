# ADR-0001: Primary local model, fallback and runtime

- **Status:** **Accepted** (2026-10-17).
- **History:**
  - **Proposed** (Phase 2, 2026-10-17). The acceptance conditions were the owner's blind naturalness rating and the owner's approval of a G2 gate revision.
  - Blind rating done 2026-10-17: Gemma 4 12B won 13 of 14.
  - **G2 revision approved by the owner, conditionally, 2026-10-17:** see "G2 revision record" below. Accepted on that basis.
- **Related:** [BENCHMARK_PLAN.md](../BENCHMARK_PLAN.md) §4–§5, [PHASE_2_MODEL_BENCHMARKS.md](../PHASE_2_MODEL_BENCHMARKS.md), [PHASE_2_REPORT.md](../PHASE_2_REPORT.md), measurement files `evals/reports/phase2/<model>/{perf,quality}.json`, `evals/reports/phase2/comparison.json`

## Decision

| Role | Model | Runtime / quantization | Digest | Disk | Resident (16K ctx) |
|---|---|---|---|---|---|
| **Primary** | Gemma 4 12B instruct | Ollama 0.40.4, llama.cpp runner, GGUF Q4_0 (Google QAT) — `gemma4:12b-it-qat` | `38044be4f923` | 7.15 GB | 7.43 GB |
| **Lightweight fallback** | Qwen3.5-9B | Ollama 0.40.4, llama.cpp runner, GGUF Q4_K_M — `qwen3.5:9b-q4_K_M` | `56671c2ab938` | 6.55 GB | 6.27 GB |
| Optional higher-quality model | none | — | — | — | — |

Operating parameters (also the config defaults):

- **Context:** `num_ctx` is 16384 for short and normal requests, and 32768 for explicit long tasks.
- **Thinking:** `think=false` by default, `think=true` only for explicit long-reasoning requests.
- **Sampling:** the model's own defaults.
- **Keep-alive:** `keep_alive=10m`.
- **Cloud:** Ollama runs with `OLLAMA_NO_CLOUD=1` on `127.0.0.1:11434`.

The runtime decision is **Ollama with its llama.cpp runner**; MLX was measured and not adopted.

## Evidence (all measured on the target Mac, AC power, no thermal warnings; typical apps open)

| | Gemma 4 12B | Qwen3.5-9B | Qwen3.5-9B MLX nvfp4 | Qwen3-14B | Qwen3-8B |
|---|---|---|---|---|---|
| Automatic quality checks (48 items) | **43** | 37 | 36 | 40 | 32 |
| Reasoning, think=false (10) | 7 | 4 | 4 | **8** | 5 |
| Reasoning set with think=true (15) / median wall time | **15/15** / 10.7 s | 11/15 / 65.6 s | 8/15 / 50.3 s | 12/15 / 11.6 s | 12/15 / 6.5 s |
| Turkish edge cases (10) | **9** | 7 | 7 | 6 | 5 |
| Instruction following (12) | **12** | 11 | 10 | 11 | 8 |
| Extraction: persons / preferences / corrections / invented-or-wrong names | **1.0 / 1.0 / 1.0 / 0** | 1.0 / 0.67 / 1.0 / 0 | 0.64 / 0.67 / 1.0 / 0 | 0.86 / 0.67 / **0.0** / 3 | 0.71 / 0.67 / 1.0 / 3 |
| JSON schema-constrained output | 100% | 100% | **unavailable** | 100% | 100% |
| "efendim" used more than once in a reply (of 60) | **2** | 7 | 2 | 18 | 15 |
| Decode tok/s (2K prompt) | 29.2 | 39.0 | 42.8 | 25.3 | 42.8 |
| Prefill tok/s (2K prompt) | 286 | 430 | 459 | 233 | 433 |
| Multi-turn TTFT p50, heavy turns (B3, 300–600-token user turns) | 1.71 s | 1.14 s | 1.18 s | 2.22 s | 1.47 s |
| Multi-turn TTFT p50, realistic short turns (20–60 tokens) | 0.79 s | 0.51 s | — | — | — |
| Resident memory at 16K / 32K | 7.43 / 7.48 GB | 6.27 / 6.84 GB | 6.75 / 6.75 GB | 10.88 / 13.45 GB | 7.25 / 9.25 GB |
| Long context (≈ 11.4K tokens, 3 facts) | 3/3 | 3/3 | 3/3 | 2/3 | 3/3 |

**Owner's blind rating** (`evals/reports/phase2/blind/ratings_owner.json`, 14 pairwise comparisons, order randomized, model names hidden):

- **Result:** Gemma 4 12B won 13, Qwen3.5-9B won 1, no ties (win rate 0.929 vs 0.071).
- **Qwen3.5's one win:** A04, where the owner preferred the shorter answer.
- **Gemma weaknesses the owner noted:**
  - wrong place facts (A06);
  - typos and grammar slips in a formal email (A09);
  - too little pushback on a mediocre poem (E05).
- **Caveat:** one rater and a small sample, so this is a strong preference, not statistical proof.

Subjective (AI evaluator, consistent with the owner's rating): Gemma's Turkish reads most natural and idiomatic. Qwen3.5 shows awkward constructions ("toplantıların ardının arkasının bittiği", "mutlu ettirsin") and mixes `sen`/`siz`. The Qwen3 models append "efendim" mechanically, even breaking exact-output tasks ("TAMAM efendim.").

## Gate check (BENCHMARK_PLAN §5.1) for the primary

| Gate | Result |
|---|---|
| G1 memory (≤ 10.5 GB, 12B class) | **Pass** for the LLM alone (7.43 GB at 16K). The B10 voice co-residency part was **not measured**: voice models are out of Phase 2 scope. Swap grew during benchmarks because typical apps were open. |
| G2 warm TTFT (p50 ≤ 1.2 s, p95 ≤ 2.5 s) | **Original G2 (300–600 new tokens per turn): FAIL** (p50 1.71 s, p95 2.43 s); this result is kept, see below. **Revised G2 (user turn ≤ 100 tokens, warm cache), approved after the results were seen: PASS** at every measured total input context from 2.2K to 11.9K tokens (p50 0.46–0.58 s with 64-token replies; 0.84–0.85 s, p95 ≤ 1.32 s with 256-token replies). Cache-miss TTFT is far above the gate (8.1 s at 2.2K → 50 s at 11.9K) and is a P3 risk, not part of G2. |
| G3 decode ≥ 20 tok/s at 8K | Pass (28.2) |
| G4 cache reuse ≥ 0.9 | **Inconclusive.** Ollama 0.40 counts cached tokens in `prompt_eval_count`, so reuse was estimated from prefill time: 0.85 median. The prefix cache demonstrably works (TTFT tracks only the new tokens). |
| G5 JSON validity | Pass (8/8 prompt-only and 8/8 schema-constrained; small sample) |
| G6 tools | **Not measured.** Tool calling belongs to the P3 framework. |
| G7 language drift ≤ 1% | Pass (0/60) |
| G8 stability | 0 crashes or hangs in ≈ 850 generations across the five models. The B8 300-turn soak was **not run**. |

## G2 revision record

**This revision was made after the benchmark results were known.** It is recorded here so that neither the original criterion nor the failed result is lost.

1. **Original gate (BENCHMARK_PLAN §5.1, Phase 0.1).** Append-only turns, ~8K history, 300–600 new tokens per turn, `think=false`, with p50 ≤ 1.2 s and p95 ≤ 2.5 s.
2. **Result under the original gate.** Gemma 4 12B **failed**: B3 heavy turns gave p50 1.71 s and p95 2.43 s. Qwen3.5-9B passed (1.14 / 1.60 s).
3. **Proposal (by the AI implementer, 2026-10-17, after seeing the results).** Measure G2 on realistic turns. 300–600-token user turns are much longer than chat or voice turns.
4. **Owner's decision (2026-10-17, conditional approval).** The owner prioritised quality: Gemma won the blind rating 13/14 and led the technical evaluations.
   - The thresholds stay the same: p50 ≤ 1.2 s, p95 ≤ 2.5 s.
   - A short interaction is **not** defined only by the user message being ≤ 100 tokens. The total input context sent to the model must also be measured and reported, because a long history can raise latency even when the user message is short.
   - The 1.71 s heavy-turn result stays in the reports, stated as **not meeting the original G2**.
5. **Revised G2 (G2-r1).**
   - Scope: append-only conversation, user turn ≤ 100 tokens, `think=false`, `num_ctx` 16384, warm prefix cache.
   - Every measurement reports the total input context the model received.
   - Same thresholds.
   - The heavy-turn scenario and the cache-miss TTFT remain **informational** and are always reported.
6. **Measurement (`evals/runners/g2_context.py`, AC power).**
   - Synthetic multi-turn histories of about 2K, 4K, 8K and 12K tokens.
   - For each size: 2 fresh histories, each with 1 cold turn (cache miss) and 5 warm short turns, so n = 10 warm turns per size.
   - New tokens per warm turn were 18–34 (user message plus chat template).

| Total input context (tokens) | Gemma warm p50 / p95 | Gemma cold (cache miss) | Qwen3.5 warm p50 / p95 | Qwen3.5 cold |
|---|---|---|---|---|
| 2,183–2,626 | 0.46 / 0.47 s | 8.1 s | 0.29 / 0.36 s | 5.6 s |
| 4,032–4,437 | 0.49 / 0.54 s | 15.2 s | 0.30 / 0.37 s | 10.4 s |
| 7,636–8,099 | 0.53 / 0.55 s | 33.9 s | 0.33 / 0.39 s | 20.2 s |
| 11,426–11,857 | 0.58 / 0.61 s | 50.3 s | 0.35 / 0.41 s | 30.6 s |

The table uses replies capped at 64 tokens. Warm TTFT also depends on the **previous reply's length**:

- With 256-token replies (`g2_context_out256`), Gemma gave 0.85 / 1.15 s at about 2K and 0.84 / 1.32 s at about 8K.
- With 150-token replies (B3 realistic, 1.9K–3.3K context), it gave 0.79 / 0.81 s.

**Probable cause (not verified):** part of the previous reply is prefilled again on the next turn (tokenization round-trip, SPK-03b). P3 must confirm this with the real prompt assembler.

**Conclusion.** Gemma 4 12B passes G2-r1 at every measured context length. It still does **not** pass the original G2. Cache misses cost 8–50 s on Gemma for 2K–12K contexts; this is the main latency risk for P3 (see Consequences).

## Why not the others

- **Qwen3-14B:**
  - largest memory (10.9 GB at 16K, 13.5 GB at 32K, with 7 GB swap growth), which leaves no room for voice;
  - slowest (22.7–25.3 tok/s, 40 s TTFT for an 8K prompt);
  - worst memory-readiness: missed every correction and extracted a corrected-away name.
- **Qwen3-8B:**
  - weakest instruction following (8/12) and edge cases (5/10);
  - "efendim" overuse breaks exact answers;
  - invented and mis-assigned names in extraction.
- **MLX runtime (`qwen3.5:9b-nvfp4`):**
  - only 7–10% faster than the same model on llama.cpp;
  - Ollama's MLX runner returns "structured output is unavailable", which the memory pipeline needs;
  - lower extraction and reasoning scores (nvfp4 vs Q4_K_M quantization).
  - Benefit worth noting: no reload when `num_ctx` changes.
- **Qwen3.5-9B as primary:** faster and smaller, but clearly weaker reasoning (4/10 without thinking, 65 s with thinking) and less natural Turkish. It remains the fallback for low-memory situations (e.g. once voice models are loaded).

## Consequences

- P3 builds on Gemma 4 12B through the `LLMProvider` port.
- **P3 latency and context risks (from the G2-r1 measurement):**
  - Any prefix-cache miss re-prefills the whole history. On Gemma this costs about 3.5–4.5 s per 1K tokens of history (8 s at 2K, 34 s at 8K, 50 s at 12K). Cache misses happen when:
    - the `keep_alive` expiry (10 min idle) unloads the model;
    - a `num_ctx` profile switch forces a reload;
    - compaction or any change to the prompt prefix;
    - a background job uses the single slot;
    - the app or Ollama restarts.
  - P3 must:
    - keep the history budget small through compaction;
    - pre-warm after idle periods and after compaction;
    - keep the prefix stable;
    - show a "preparing" state instead of a silent wait.
  - Warm TTFT grows with history (0.46 → 0.58 s from 2K to 12K) and with the previous reply's length. G2-r1 must be re-measured with the real assembler and real reply lengths (CNV-01).
- P13 must re-check memory with the voice models: 7.4 GB LLM plus STT/TTS on a 24 GB machine with typical apps already showed swap growth.
- Persona work (P5) must address the address-form consistency (`sen` vs `siz` with "efendim") seen in all models, plus the pushback and brevity issues from the owner's rating.
- P3 should treat the model's place and fact claims as unverified (the owner's A06 note).
