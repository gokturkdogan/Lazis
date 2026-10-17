# LAZIS — Benchmark and Evaluation Plan

> Status: Phase 0.1 (new document) · Last updated: 2026-10-17
> Applies to: **P2** (LLM, embeddings, voice feasibility smoke), **P13** (voice), and every later gate (regression). **No benchmark in this plan has been run yet.** Rationale for the candidates: [TECHNOLOGY_DECISIONS.md](TECHNOLOGY_DECISIONS.md). Test layers: [TESTING_STRATEGY.md](TESTING_STRATEGY.md).

## 1. Principles and environment control

1. **Reproducible:** every run is scripted (`just bench <suite>`, `just eval <suite>`). Prompts, datasets, sampling settings and model digests are versioned. Raw outputs are kept.
2. **Controlled environment:** the target Mac on **AC power**, after a 60 s thermal settle, with other heavy applications closed, unless a test explicitly measures "typical apps open". Each report records the power and thermal state (`pmset -g batt`, `pmset -g therm`).
3. **Repetition:** 1 warm-up run plus ≥ 10 measured runs per latency scenario. Report the median, p95 and spread, never a single best run.
4. **Measured ≠ published:** model-card or third-party numbers are never used as results. Anything not measured stays labeled *(est.)*.
5. **Decisions follow pre-declared rules** (§5, §7.6). Any change to a gate after seeing the results requires an ADR approved by the user.
6. **Privacy:** benchmark datasets are fictional. The user's own voice recordings (P13) are stored outside the repository, in the encrypted data directory, and only metrics are committed.

**Environment manifest** (captured automatically into every report): machine model, macOS version, Ollama version, model tags and digests, runner observed per tag (`OLLAMA_DEBUG=1` logs), `num_ctx`, Ollama environment variables, sampling parameters, power/thermal state, and summary memory state at start (`vm_stat`, `sysctl vm.swapusage`).

## 2. Candidates and variants (P2)

| Model | Variants to test | Notes |
|---|---|---|
| **Qwen3.5-9B** (primary candidate) | `9b` (GGUF q4_K_M, 6.6 GB) · `9b-nvfp4` (MLX, 7.2 GB) · `9b-mlx` (MLX, 8.9 GB) · `9b-q8_0` (10 GB) for quality comparison | Runner identified per tag (SPK-08). MTP tags are tested for decode speed only if memory allows |
| **Gemma 4 12B** (challenger) | `12b-it-qat` (7.2 GB) · `12b-nvfp4` (MLX, 7.7 GB) | Standard attention; a reference point for prefill on hybrid models |
| Qwen3-14B (baseline from the brief) | `14b` q4_K_M (9.3 GB) | — |
| Qwen3-8B (baseline from the brief) | `8b` q4_K_M (5.2 GB) | — |
| *(optional)* Qwen3.5-4B | `4b` | Battery-profile candidate only |

Embedding candidates (B9): Qwen3-Embedding-0.6B, EmbeddingGemma-2 (270M text), BGE-M3 (reference).
Engines: Ollama 0.40.x (primary). `mlx_lm.server` and `llama-server` are tried only when a gate fails on Ollama (§5.3).

## 3. Datasets (fictional personas only)

| Dataset | Size | Used by |
|---|---|---|
| Turkish naturalness prompts (casual, emotional, advice, humor) | 60 | B5 |
| Instruction-following checks (`sen`/`siz`, length, no emoji, banned phrases) | 40 | B5 |
| Pushback set (wrong claims, risky plans, requests for validation) | 30 | B5 |
| Extraction gold dialogues (annotated claims, entities, evidence quotes, sensitivity) | 100 | B6 |
| JSON stress prompts (long, nested quotes, Turkish characters, empty-result cases) | 40 | B6 / SPK-02 |
| Tool-call cases (remember/forget/search/correct) + no-tool controls | 50 + 30 | B7 |
| Synthetic long conversation (scripted persona, 300 turns) | 1 | B3, B8 |
| Retrieval pairs (query → memory; incl. diacritic-less and inflected names) | ≈ 300 | B9 |
| Turkish TTS sentence suite (§7.1) | 64 + 1 passage | V2 |
| User's own STT recordings (§7.2) | ≈ 230 | V1 (stored privately) |

## 4. LLM benchmarks (P2)

**Metric definitions** (Ollama response fields + wall clock):
- **TTFT** = request sent → first *content* token received (thinking tokens excluded; `TTFT_any` includes them).
- **Prefill throughput** = `prompt_eval_count / prompt_eval_duration`, cross-checked against wall clock.
- **Decode throughput** = `eval_count / eval_duration`.
- **Cache reuse ratio** = `1 − prompt_eval_count / prompt_tokens`, where `prompt_tokens` is counted locally with the model's tokenizer. Count parity with Ollama is verified first.
- **Resident memory** = Ollama `/api/ps` (`size`, `size_vram`) + `footprint`/RSS of the runner process + system `vm_stat` (wired, compressed) + swap usage.

| ID | Benchmark | Procedure | Outputs |
|---|---|---|---|
| **B1** | Cold model load | (a) *warm-cold*: model unloaded (`ollama stop`), file cache warm; (b) *cold-cold*: after `sudo purge` (optional, needs the user's password). Request with a 1-token output; 5 runs each | load time, first-response time, runner observed |
| **B2** | Warm single-turn latency | Prompts of 512 / 2K / 8K / 16K tokens (Turkish chat histories), 128-token output, `think=false`, no prefix reuse (distinct prompts) | TTFT, prefill tok/s, decode tok/s per size |
| **B3** | Multi-turn cache behavior | Scripted 20-turn append-only session (2K → ~10K tokens, 300–600 new tokens per turn). Variants: (a) mid-prefix change (profile block edited) → expected miss; (b) compaction + pre-warm, then the next turn; (c) `think=true` turns (template rewriting of history); (d) after a model reload; (e) **background extraction request between turns** with the same `num_ctx`, under `OLLAMA_NUM_PARALLEL=1` vs `2`; (f) tokenization round-trip drift check (generated tokens vs. re-tokenized history) | per-turn TTFT, `prompt_eval_count`, reuse ratio; miss causes |
| **B4** | Memory consumption | (a) loaded and idle at the pinned `num_ctx`; (b) peak during a 16K prompt; (c) LLM + embedding model co-resident; (d) + voice smoke models (B10); (e) 30 min with typical apps open (browser, editor), recording swap and memory pressure | GB per component, swap delta, pressure level |
| **B5** | Turkish response quality | Generate for all prompts per candidate with fixed sampling. **Blind pairwise rating by the user** (randomized order, model identity hidden) through a local rating CLI or page. Automated checks for instruction following and drift. Pushback rated by rubric | win rate, violation rate, pushback rate, drift % |
| **B6** | Structured JSON extraction | 100 gold dialogues with the production extraction schema, `think=false` (and `true` for comparison); JSON stress prompts (SPK-02) | first-try validity, validity after one repair, field-level P/R/F0.5, evidence-quote validity |
| **B7** | Tool calling (Turkish) | 50 tool cases + 30 no-tool controls with the production tool definitions | correct tool %, argument accuracy, false-call % |
| **B8** | Long conversation | 300-turn scripted session with idle-time compaction enabled | TTFT per turn (trend), compaction count, context errors, crash/hang count, drift over time, runner RSS trend |
| **B9** | Embedding retrieval | Retrieval set at full dimension and MRL truncations (512/256) | recall@10, nDCG@10, diacritic-less and inflected subsets, query latency, model memory |
| **B10** | Voice feasibility smoke (SPK-07) | Primary LLM candidate loaded, then Whisper large-v3-turbo + one TTS candidate at a time (Chatterbox Multilingual; one alternative). Synthesize 5 Turkish sentences and transcribe them back | co-resident memory, RTF, swap; **no quality judgment** |

## 5. LLM gates, scoring and decision rules

### 5.1 Hard gates (every one must pass)

| Gate | Criterion | From |
|---|---|---|
| **G1 Memory** | Primary LLM resident at pinned `num_ctx` ≤ 9.0 GB (9B class) / ≤ 10.5 GB (12B class); B10 combination (LLM + embedding + STT + TTS) leaves LAZIS ≤ 14 GB total with **no swap growth** over 30 min with typical apps | B4, B10 |
| **G2 Warm TTFT** | Append-only turns, ~8K history, 300–600 new tokens, `think=false`: p50 ≤ 1.2 s, p95 ≤ 2.5 s | B3 |
| **G3 Decode** | ≥ 20 tok/s median at 8K | B2 |
| **G4 Cache reuse** | Reuse ratio ≥ 0.9 on ≥ 95% of append-only turns, including turns after a background job (B3e) under the chosen `NUM_PARALLEL` setting | B3 |
| **G5 JSON** | ≥ 97% valid first try; ≥ 99% after one repair | B6 |
| **G6 Tools** | Correct tool ≥ 95%; false calls ≤ 2% | B7 |
| **G7 Language drift** | ≤ 1% of responses | B5–B8 |
| **G8 Stability** | 0 crashes or hangs; 0 context-overflow errors in B8 | B8 |

Informational (no gate): cold load time (B1), prefill throughput (B2), latency trend over long sessions (B8).

### 5.2 Weighted score (only among candidates that pass all gates)

| Component | Weight | Measure |
|---|---|---|
| Turkish naturalness | 40 | B5 blind pairwise win rate |
| Extraction quality | 25 | B6 F0.5 (precision-weighted) |
| Pushback appropriateness | 15 | B5 rubric |
| Instruction following | 10 | B5 (1 − violation rate) |
| Latency | 10 | G2 p50, normalized |

### 5.3 Decision rules
1. The highest score wins. Within 3 points, prefer the lower memory footprint, then the more mature runner path.
2. **Variant choice** for the winning model: the smallest-memory variant whose naturalness and extraction scores are within 2 points of that model's best variant.
3. **If no candidate passes all gates:**
   - fails only G2 or G4 → re-run B2/B3 for that model through `mlx_lm.server` or `llama-server` (`OpenAICompatLLMProvider`) before rejecting it;
   - fails G5 → test grammar-constrained decoding on the llama.cpp path;
   - fails G7 → test the Q8 / MLX 8-bit variant and tune presence penalty;
   - otherwise → present the options to the user. **Any gate relaxation requires an ADR approved by the user.**
4. **User veto on naturalness:** the final recommendation is presented with side-by-side samples, and the user may reject it.
5. **Results produce:** ADR-0001 (model + variant + engine + `num_ctx` + `NUM_PARALLEL` + sampling) and ADR-0002 (embedding model + dimension).

### 5.4 Embedding decision rule (B9)
Pick the smallest model and dimension whose recall@10 is within 2 points of the best and whose diacritic-less recall is within 5 points of its plain recall. Query latency must be ≤ 25 ms (warm, p50).

## 6. Cache-reuse investigation detail (SPK-03)

| Hypothesis | Test | If false |
|---|---|---|
| H1: Append-only turns reuse the slot cache | B3 base run | Try the alternative engine; if every engine fails, shrink voice prompts and accept higher TTFT (ADR) |
| H2: `prompt_eval_count` reflects only newly evaluated tokens | Compare with wall-clock prefill time and local token counts | Use a timing-based miss detector instead |
| H3: Re-rendered assistant turns tokenize identically to the generated tokens | B3f | Store and replay the generated token IDs when the engine accepts raw prompts; else accept one partial re-prefill per turn |
| H4: Background requests do not evict the conversation cache | B3e with `NUM_PARALLEL=1` | Use `NUM_PARALLEL=2` (separate slot; the KV cost is small for hybrid models) **or** re-warm the conversation prefix during idle after each background job |
| H5: Pre-warm after compaction makes the next turn warm | B3b | Compact earlier and at natural pauses; accept one slower turn |

## 7. Voice evaluation (P13)

### 7.1 TTS evaluation suite (Turkish)

**Target voice:** male, slightly deep, warm, natural, expressive, comfortable for long conversations, with clear Turkish pronunciation.

| Category | Count | Examples (fictional) |
|---|---|---|
| Everyday conversational sentences | 10 | "Bugün biraz yorgun görünüyorsun, dün gece iyi uyuyabildin mi?" |
| Long sentences (30–45 words) | 5 | "Yarın sabah erkenden yola çıkarsak öğleden önce Eskişehir'e varır, kısa bir moladan sonra akşam yemeğine kadar Ankara'da oluruz diye düşünüyorum, ama trafiğe göre plan değişebilir." |
| Questions (yes/no and wh-) | 6 | "Yarınki toplantıya sen de katılacak mısın?" · "Bunu neden böyle düşündüğünü anlatır mısın?" |
| Emotional expressions | 6 | "Çok geçmiş olsun, umarım en kısa sürede iyileşirsin." · "Vay, bu gerçekten harika bir haber!" · "Bunu yaşamak hiç kolay olmamalı." |
| Proper names | 6 | "Ilgaz, Çağrı ve Gülşah cumartesi Kadıköy'de buluşacak." · "Eskişehir'den Diyarbakır'a uzun bir yolculuk." |
| Numbers | 6 | "Toplam 1.250,50 TL tuttu." · "Oran %15'ten %22,5'e çıktı." · "Yaklaşık 3,5 milyon kişi." |
| Dates and times | 5 | "Toplantı 17 Ekim 2026 Cumartesi, saat 14:30'da." · "1923'te kuruldu." |
| Abbreviations | 5 | "ODTÜ, TBMM ve THY hakkında konuştuk." · "Dr. Yılmaz vb. konularda yardımcı oldu." |
| Foreign names used in Turkish | 5 | "Netflix'te bir Shakespeare uyarlaması izledik." · "iPhone'un yeni sürümü GitHub'da da konuşuluyor." |
| Turkish-specific characters and sounds | 5 | "Kartal kalkar dal sarkar, dal sarkar kartal kalkar." · "Ilık bir rüzgâr ılgın ağaçlarının arasından geçti." · "Şu köşe yaz köşesi, şu köşe kış köşesi." |
| Natural pauses and hesitation | 5 | "Şey… aslında, düşününce, bu fikir hiç de fena değil." · "Bir dakika—bunu daha önce konuşmuştuk, değil mi?" |
| Long-form passage (~3 min) | 1 | listening comfort and stability over time |

**Procedure:** every candidate synthesizes the same normalized text (the production TTS normalizer is applied first), with the same reference voice for cloning models and the best available male voice for fixed-voice models. Outputs are loudness-normalized (EBU R128, −23 LUFS), presented in randomized blind order, and rated by the user 1–5 on each dimension. Each of 10 sentences is synthesized 5 times to measure stability.

| Dimension | Measure |
|---|---|
| Pronunciation | ASR round-trip CER per category (Whisper large-v3) + the user's 1–5 rating |
| Naturalness | the user's MOS 1–5 |
| Male-voice suitability (slightly deep, warm) | the user's 1–5 rating; median F0 reported for information |
| Expressiveness | the user's 1–5 rating on emotional sentences and questions |
| Stability | skipped/repeated/garbled words per sentence (alignment-based) across the 5 repeats; drift over the 3-minute passage |
| Latency | time-to-first-audio for a 6–10-word first clause (warm), RTF |
| Resources | peak memory, GPU/CPU share during synthesis |
| Streaming | native streaming vs. sentence-level only |
| Licensing | personal-use acceptability (recorded, gating) |

### 7.2 STT evaluation suite

The user records the utterances (scripted prompts, fictional content). Noise conditions are mixed in programmatically.

| Category | Count | Description |
|---|---|---|
| Normal speech | 20 | clear, close to the built-in mic |
| Fast speech | 20 | natural fast pace |
| Quiet / far speech | 20 | low voice, ~1.5 m from the laptop |
| Background noise | 30 | café / TV / fan, mixed at SNR 10 dB and 5 dB |
| Informal Turkish | 25 | "napıyosun", "gidicem", "bi' bakayım", "hıı tamam" |
| Proper names | 25 | fictional people, places, brands from the eval persona's graph |
| Interrupted / self-corrected speech | 20 | "yarın, yok yok, perşembe" · mid-sentence restarts |
| Long utterances | 10 | 20–30 s |
| Numbers and dates | 15 | amounts, times, dates |
| Code-switching | 15 | "deploy'u yarına attık", "meeting'i iptal ettiler" |
| Silence / noise only | 30 | hallucination check |

WER and CER use Turkish normalization: casefold, punctuation removal, number normalization, apostrophe-suffix normalization. Candidates: Whisper large-v3-turbo (mlx-whisper; whisper.cpp + CoreML), Whisper large-v3 (accuracy reference), a Turkish fine-tuned turbo, and Qwen3-ASR 1.7B/0.6B (if a maintained Apple-Silicon runtime exists at test time).

### 7.3 Turn-taking
- **Hesitation set** (40 utterances with 0.5–1.5 s mid-sentence pauses, "şey…", lists): premature cut-off rate; endpoint latency (last speech frame → commit).
- **Continuation set** (user adds a sentence right after commit): correct merge-and-resubmit behavior.
- **Backchannel set** ("hı hı", "evet", "tamam" during LAZIS speech): must not interrupt.

### 7.4 Echo cancellation and barge-in (SPK-09)
A synthetic echo harness plays LAZIS speech through the real output path (built-in speakers, external speakers, headphones) while injecting pre-recorded user speech at known offsets. Measures: duck latency, flush latency, barge-in precision and recall, false barge-ins per 10 minutes of LAZIS speech, and self-transcription of LAZIS audio (must be 0 in AEC mode).

### 7.5 End-to-end latency decomposition
Each voice turn logs `t_speech_end`, `t_turn_commit`, `t_stt_done`, `t_request_sent`, `t_first_token`, `t_first_clause`, `t_first_pcm` and `t_playback_started`. Reports show p50/p95 **per stage** and for the total, over ≥ 100 turns. The planning budgets in [TECHNOLOGY_DECISIONS.md §8.3](TECHNOLOGY_DECISIONS.md) are replaced by these measurements.

### 7.6 Voice gates and decision rules

| Component | Hard gates | Soft score |
|---|---|---|
| **TTS** | CER ≤ 5% overall, no category > 10% (foreign names ≤ 15%) · time-to-first-audio ≤ 600 ms p50 warm † · RTF ≤ 0.7 † · peak memory ≤ 2.5 GB · instability ≤ 2% of sentences · no degradation over the 3-min passage · license acceptable | MOS: naturalness 30 · pronunciation 25 · male-voice suitability 20 · expressiveness 15 · long-listening comfort 10. Highest wins; ties → lower latency; **user veto** |
| **STT** | WER ≤ 12% † and CER ≤ 5% on close-mic categories · proper names ≥ 85% · numbers ≥ 90% · ≤ 1 hallucination in 30 silence clips · 5 s utterance transcribed ≤ 600 ms p50 warm † · memory ≤ 2 GB | WER by category: informal 25 · noisy 20 · names 20 · fast 15 · quiet 10 · long 10 |
| **Turn-taking / barge-in** | premature cut-off ≤ 5% · endpoint latency p50 ≤ 400 ms † · duck ≤ 300 ms p95 · false barge-ins ≤ 1 per 10 min on built-in speakers (else the fallback mode must be approved) | — |
| **End-to-end** | per-stage report complete; total p50 ≤ 1.8 s, p95 ≤ 3.0 s † | — |

Targets marked † are provisional and may be revised only through an ADR approved by the user, using the measured data.

## 8. Reporting and reproducibility

- Each run writes `evals/reports/YYYY-MM-DD-<suite>.md` (summary) plus `…-raw.jsonl` (all prompts, outputs and timings), and an environment manifest.
- **Report template:** environment manifest · candidates and variants · commands executed · per-benchmark results with medians/p95 · gate table (pass/fail with numbers) · weighted scores · decision per the declared rules · anomalies and skipped tests with reasons · links to the resulting ADRs.
- Rating sessions record the rater (the user), the date and the blind mapping (revealed only after rating).

## 9. Regression policy
- B2/B3/B5-subset/B6/B7 re-run whenever the model, the engine version, prompts, the persona or the extraction schema changes. V-suites re-run when voice components change.
- A regression beyond 10% on any gated latency metric, or any gate falling below its threshold, blocks the phase gate until it is fixed or accepted by an ADR.
