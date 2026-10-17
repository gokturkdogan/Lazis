# LAZIS — Technology Decisions

> Status: Phase 0.1 (revised), updated after Phase 1 (§12: stack as built; SPK-04/05 done) · Research date: 2026-10-17 · Target: MacBook Pro M4 Pro (14 CPU / 20 GPU cores, Metal 4), 24 GB, macOS 27.0.1
> Convention: **Decision** = adopted for implementation. **Provisional** = adopted pending a named measurement (spike `SPK-xx`, §10). **Rejected** = considered and declined, with the reason.
> Figures marked *(est.)* are engineering estimates, not measurements. **Nothing in this document has been benchmarked on the target machine yet.** Everything marked **VERIFY** is a scheduled spike. The measurement protocol and pass/fail gates are in [BENCHMARK_PLAN.md](BENCHMARK_PLAN.md).

## 0. Verified environment (2026-10-17)

| Item | Found on machine |
|---|---|
| Hardware | Mac16,7 MacBook Pro, Apple M4 Pro, 14 CPU cores, 20-core GPU, Metal 4, 24 GB (25,769,803,776 bytes) |
| OS | macOS 27.0.1 (26A434) |
| GPU wired limit | `iogpu.wired_limit_mb = 0` (system default) |
| Ollama | 0.40.4 installed, no models pulled; exposes `OLLAMA_NO_CLOUD`, `OLLAMA_KV_CACHE_TYPE`, `OLLAMA_CONTEXT_LENGTH`, `OLLAMA_KEEP_ALIVE`, `OLLAMA_NUM_PARALLEL` |
| Toolchains | Rust 1.99.1, Node 24.10, pnpm 10.28, Swift 6.4, Docker 28.4 (installed but **not used**: LAZIS must not depend on Docker), Homebrew Python 3.14/3.15 (system 3.9.6 is unsuitable); `uv` not installed at Phase 0 — P1 installed uv 0.13.1, which manages CPython 3.13.16 |
| Disk | 121 GiB free (model set needs ~30–40 GB) |
| Power | Laptop, on battery at time of check → benchmarks must run on AC power |

---

## 1. Local LLM selection

### 1.1 What changed since the original brief

The brief proposed **Qwen3 8B / 14B** (April 2025). Several newer generations have shipped since, and they matter for this hardware:

- **Qwen3.5** (Feb–Mar 2026): 0.8B/2B/4B/**9B** dense plus 27B and MoE models. Apache 2.0, natively multimodal, 262K context, 201 languages. It uses a **hybrid Gated-DeltaNet architecture**: only 1 in 4 layers uses full attention, which shrinks the KV cache dramatically.
- **Qwen3.6** (Apr 2026: 27B dense, 35B-A3B MoE) and **Qwen3.8-27B** (Aug 2026): strong, but all at 27B+.
- **Gemma 4** (Apr 2026: E2B, E4B, 26B-A4B MoE, 31B; **12B** added Jun 2026). Apache 2.0, 140+ languages, native function calling, configurable thinking; the 12B also accepts audio input.

### 1.2 Model selection matrix

KV-cache figures are computed from the published model configs (fp16 KV). Sizes come from the Ollama library (Q4-class tags).

| Model | Arch | Ollama size (Q4) | KV cache / token | KV @16K | Est. resident @16K | Turkish evidence | Tools / JSON | Thinking control | License | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| **Qwen3.5-9B** | Hybrid: 32 layers, 8 full-attn (4 KV heads × 256), 24 Gated-DeltaNet; MTP | 6.6 GB (`q4_K_M`); 7.2 GB MLX `nvfp4` | **32 KiB** | **0.5 GiB** | ~7.5–8 GB *(est.)* | 201 languages claimed; MMMLU 81.2, MMLU-ProX 76.3, INCLUDE 75.6, WMT24++ 72.6 (model card). No Turkish-only score | Yes / yes | `enable_thinking` (Ollama `think`) | Apache 2.0 | **Primary candidate** |
| **Gemma 4 12B** | Dense, sliding-window (1024) + global attention, encoder-free multimodal (text/image/audio) | 7.2 GB (`it-qat`), 8.0 GB (`q4_K_M`) | moderate (mostly local layers) — **VERIFY** | ~1 GiB *(est.)* | ~9–10 GB *(est.)* | 140+ languages claimed; no Turkish-only score found | Native function calling / yes | Configurable thinking | Apache 2.0 | **Challenger** |
| Qwen3-14B (brief) | Dense, 40 layers, 8 KV heads × 128 | 9.3 GB | 160 KiB | 2.5 GiB | ~12–12.5 GB *(est.)* | 119 languages claimed | Yes / yes | `/think` soft switch | Apache 2.0 | Baseline only: tight with voice, slower |
| Qwen3-8B (brief) | Dense, 36 layers, 8 KV heads × 128 | 5.2 GB | 144 KiB | 2.25 GiB | ~7.5–8 GB *(est.)* | 119 languages claimed | Yes / yes | `/think` | Apache 2.0 | Baseline only: superseded by Qwen3.5-9B |
| Qwen3.5-4B | Hybrid (as 9B, smaller) | 3.3 GB | small | small | ~4 GB | as 3.5 family | Yes / yes | yes | Apache 2.0 | Low-power / auxiliary fallback |
| Gemma 4 E4B | Edge, audio input | 6.1–6.6 GB | — | — | ~7 GB | 140+ languages | Yes | yes | Apache 2.0 | Rejected: same footprint as the 9B, weaker |
| Qwen3.5/3.6/3.8-27B | Hybrid dense 27B | 16–20 GB | 64 KiB | 1 GiB | 18–22 GB | strong | Yes | yes | Apache 2.0 | **Rejected for 24 GB**: no headroom for OS + voice |
| Qwen3.5/3.6-35B-A3B | MoE, 3B active | 20–22 GB | — | — | > 22 GB | strong | Yes | yes | Apache 2.0 | Rejected: does not fit |
| Gemma 4 26B-A4B | MoE, 4B active | 16–19 GB | — | — | ~18–20 GB | strong | Yes | yes | Apache 2.0 | Rejected: fast but leaves < 4 GB for everything else |
| Turkish fine-tunes (Trendyol-LLM-8B-T1, Cosmos Turkish-Llama-8B, Kocdigital-LLM-8B) | 8B dense | ~5 GB | ~128 KiB | ~2 GiB | ~7.5 GB | Turkish-specialized | Unknown / weak | — | various | Optional bake-off reference for Turkish fluency only |

### 1.3 Decision: primary model (provisional)

**Provisional primary: Qwen3.5-9B.** The tag, quantization and runner are **not yet fixed**. The default Ollama tag `qwen3.5:9b` is a GGUF `q4_K_M` build (6.6 GB), which most likely runs on the llama.cpp runner. The MLX runner applies to the MLX-format tags (`9b-nvfp4` 7.2 GB, `9b-mlx` 8.9 GB). Phase 0 wrongly implied that the default tag runs on MLX. The P2 bake-off compares both runner paths ([BENCHMARK_PLAN.md §2](BENCHMARK_PLAN.md)) and picks the variant.

Reasons:
1. **Memory efficiency on 24 GB.** The hybrid architecture makes long context almost free: 0.5 GiB of KV at 16K tokens, versus 2.25–2.5 GiB for Qwen3-8B/14B. That leaves room for STT + TTS + embeddings + UI at the same time. See §8.
2. **Best documented multilingual results in the size class** among models that fit (MMMLU 81.2, INCLUDE 75.6). Turkish is not reported separately, so this must be measured.
3. **Tool calling and thinking control** are supported first-class by Ollama for this family, and thinking can be disabled per request for voice latency.
4. **Apache 2.0**, mainstream support (Ollama MLX runner, llama.cpp, mlx-lm), with MTP variants available for speculative decoding.

**Challenger: Gemma 4 12B (QAT).** The Gemma family has a strong multilingual reputation and native function calling. It also has audio input, a possible future path to direct speech understanding. It costs about 1.5–2 GB more and decodes about 20–25% slower *(est.)*.

**Single resident LLM.** The same model serves conversation, memory extraction and research summarization. Two resident LLMs would cost 5–8 GB, the margin we need for voice. If extraction quality requires it, a dedicated extraction prompt with structured output is preferred over a second model.

### 1.4 Not selecting on benchmarks alone

The P2 bake-off scores each candidate on **LAZIS-specific Turkish tasks** run on this Mac: naturalness rated blind by the user, instruction following, pushback, JSON extraction, tool calling, language drift, latency, cache behavior and memory. The Turkish eval set uses fictional personas only. The full protocol, metric definitions, **hard gates (G1–G8)**, weighted scoring and decision rules are in [BENCHMARK_PLAN.md §5](BENCHMARK_PLAN.md). In short: a candidate must pass every hard gate. Among those that pass, Turkish naturalness and extraction precision outweigh raw speed.

### 1.5 Quantization policy (provisional)

- Start at **Q4-class** (`q4_K_M` GGUF or MLX `nvfp4`/4-bit) for the 9–12B candidates. Compare against **Q6/Q8** in the bake-off: on Qwen3.5-9B, `q8_0` costs 10 GB and may improve Turkish morphology.
- KV cache: f16 by default. `OLLAMA_KV_CACHE_TYPE=q8_0` is only worth testing on full-attention models; the KV is already small on the hybrid ones.

### 1.6 Assumption review (Phase 0.1)

The model selection is **kept** (Qwen3.5-9B primary, Gemma 4 12B challenger, Qwen3-14B and Qwen3-8B baselines). Nothing found in this review justifies changing it before measurement. The assumptions behind it were re-examined:

| # | Assumption | Status | Evidence / correction | Action |
|---|---|---|---|---|
| A1 | All candidates run on the M4 Pro via Ollama 0.40.4 | **Partly verified** | Ollama 0.40.4 is installed. The library lists `qwen3.5`, `gemma4` and `qwen3` tags with MLX and GGUF variants. No model has been pulled or run | P2: pull, run, record the runner per tag (SPK-08) |
| A2 | The default `qwen3.5:9b` tag runs on the MLX runner | **Corrected** | The default tag is GGUF `q4_K_M`. MLX applies to MLX-format tags (`nvfp4`, `mlx`, `mxfp8`), and Ollama documents no command that shows the active runner | Bench both runner paths; identify the runner via `OLLAMA_DEBUG=1` logs |
| A3 | 24 GB is enough for LLM + voice + UI | **Estimated** (§8.1) | Arithmetic from published file sizes and configs, not measured. Ollama may size its allocation from `num_ctx`, not from the tokens actually used | Pin `num_ctx`; measure resident memory at the pinned context (G1) |
| A4 | Ollama's default context is safe | **Risk identified** | `OLLAMA_CONTEXT_LENGTH` defaults to "4k/32k/256k based on VRAM" (local `ollama serve --help`). On this machine the default may be large, and changing `num_ctx` between requests can force a model reload | Set one explicit `num_ctx` for all request types (§2.2) |
| A5 | KV cache ≈ 32 KiB/token for Qwen3.5-9B | **Computed, unverified** | From the model card: 8 full-attention layers × 4 KV heads × 256 dim × K+V × fp16. The Gated-DeltaNet recurrent state (~25–50 MB) is fixed size. Engine overheads are unknown | Measure at 4K/16K/32K (B4) |
| A6 | Prefill of 350–700 tok/s for Qwen3.5-9B | **Low-confidence estimate** | Extrapolated from dense ~8B models on M4 Pro-class GPUs. Gated-DeltaNet kernels on Metal/MLX may be less optimized than standard attention, so hybrid prefill could be slower *or* faster | Measure (B2). Gemma 4 12B (standard attention) is the ready challenger |
| A7 | Decode of 30–40 tok/s | **Estimate** (bandwidth arithmetic) | 273 GB/s ÷ ~5.2 GB/token × 0.6–0.75 efficiency | Measure (B2) |
| A8 | Prefix (KV) cache reuse across turns | **Unverified** | See §2.1. Not guaranteed for hybrid recurrent models, MLX runners, or when the chat template rewrites history | Spike SPK-03, gate G4 |
| A9 | JSON-schema structured output is grammar-enforced | **Unverified on MLX** | Ollama supports `format` with a schema. Enforcement on the MLX runner is undocumented (XGrammar is mentioned in v0.34.4 notes) | SPK-02: stress test with schema-violating prompts; validation and repair are mandatory either way |
| A10 | Tool calling is reliable in Turkish | **Unverified** | The model card claims strong tool calling, in English-centric evaluations | B7 tool-call set in Turkish |
| A11 | Turkish quality is adequate | **Unverified** | 201 languages claimed; multilingual aggregates only; no Turkish-only score | B5 blind ratings by the user (decisive) |
| A12 | Model switching is not needed at runtime | **Design decision** | Single resident LLM; switching costs a reload (cold-load time is measured in B1) | Bake-off switches models offline only |
| A13 | Quantization (Q4) is good enough for Turkish | **Unverified** | Turkish morphology may suffer at 4-bit | Compare Q4 vs Q8 / MLX 8-bit for the winner (B5, B6) |

---

## 2. Inference engine

| Criterion | **Ollama 0.40.x** | MLX-LM (`mlx_lm.server`) | llama.cpp (`llama-server`) | LM Studio |
|---|---|---|---|---|
| Apple Silicon speed | MLX runner by default for supported architectures since v0.40.0 (qwen3.5, gemma4, qwen3.6, qwen3.8); GGUF via llama.cpp otherwise | Native MLX: typically fastest | Metal backend, mature | MLX + llama.cpp engines |
| Structured output | JSON-schema `format`; XGrammar updated in v0.34.x — **VERIFY on MLX runner** | Not native (needs an outlines-style add-on) | GBNF / JSON schema, very mature | Yes |
| Tool calling | Native, per-model parsers | Partial, model-dependent | `--jinja` templates | Yes |
| Thinking control | `think` param; `/api/show` reports thinking controls (v0.34.3) | chat template kwargs | template kwargs | Yes |
| Model management | Pull/pin by digest, `keep_alive`, multi-model scheduling | Manual (HF cache) | Manual (GGUF files) | GUI |
| Embeddings | Yes (EmbeddingGemma-2 on MLX in 0.40) | Separate libs | Yes | Yes |
| Prefix/prompt cache | Automatic per slot — **VERIFY with hybrid models** | Prompt cache supported | Slot save/restore, most controllable | Yes |
| Privacy | Cloud features exist; **`OLLAMA_NO_CLOUD=1` disables remote inference and web search** (verified locally) | Fully local | Fully local | Closed-source app |
| Fit for LAZIS | **Decision: primary** | Alternative provider / experiments | Alternative provider / exit strategy | Not used as a dependency |

**Decision:** Ollama is the primary engine, accessed only through `LLMProvider`. An `OpenAICompatLLMProvider` covers `mlx_lm.server` and `llama-server` from P2, so switching engines is a configuration change.

**Risks and mitigations:**
- *Cloud drift and auto-upgrade.* v0.40.2 introduced background model upgrades, which v0.40.3 then paused. Mitigations: `OLLAMA_NO_CLOUD=1`, models pinned by digest in `config/defaults.toml`, digests verified at startup, refusal to run on mismatch, Ollama version pinned and upgraded deliberately.
- *Rapid release cadence* (0.30 → 0.40 in five months). The provider contract test suite runs against every new Ollama version before it is adopted.

**Rejected:** in-process MLX inference inside `lazis-core` for the LLM. GPU memory management, crash isolation and model lifecycle are better owned by a dedicated server. Smaller MLX models (STT/TTS) do run in-process.

### 2.1 Context caching: what is and is not guaranteed

Phase 0 made the prompt **append-only** so that each turn would only prefill new tokens. Keeping the conversation history does **not** by itself guarantee KV-cache reuse. The answers to the open questions:

| Question | Analysis | Consequence |
|---|---|---|
| 1. Does the backend support the required caching? | Ollama's llama.cpp-based runner reuses the KV cache for the longest common token prefix within a slot. That is a documented behavior of llama.cpp's server, but the exact Ollama behavior must be confirmed. For **hybrid/recurrent** layers (Gated DeltaNet), state cannot be truncated to an arbitrary earlier point: reuse works only if the new prompt **strictly extends** the cached one, unless the engine keeps state checkpoints. **Caching on Ollama's MLX runner is undocumented.** mlx-lm's own server keeps a prompt cache and, by its design, can reuse non-trimmable caches only when the prompt extends the cached one | **Unverified for our exact setup → SPK-03.** The append-only layout is the right design for every engine, but whether it pays off has to be measured |
| 2. Do prefixes stay stable? | Not automatically. Causes of instability: timestamps or retrieved memories in the system prompt; non-deterministic serialization (dict order, tool order); chat templates that **rewrite earlier turns**, for example by stripping previous reasoning blocks when thinking is on; and **tokenization round-trip drift**, where the tokens generated for an assistant turn differ from the tokens produced by re-tokenizing its text in the next request | Rules: the static prefix contains no time or retrieval content; serialization is canonical (sorted keys, fixed tool order); voice and extraction use `think=false`; the round-trip drift is measured (SPK-03b) |
| 3. How does memory retrieval affect reuse? | If retrieved memories were placed in the system prompt, every turn would invalidate the cache. In our layout they are attached to the **current user turn** and stay in the history | Reuse is preserved. Cost: the context grows faster, which the already-in-context dedupe limits ([MEMORY_ARCHITECTURE.md §18.1](MEMORY_ARCHITECTURE.md)) |
| 4. How does summarization (compaction) affect reuse? | Compaction rewrites the prefix, so the **next request is a full cold prefill** | Compaction runs only while idle, followed by a **pre-warm request** with the new prefix (minimal output tokens). The technique is verified in SPK-03 |
| 5. What happens when the context window is exceeded? | Engines silently truncate or shift context when the prompt exceeds `num_ctx`. The application must never rely on that | `lazis-core` counts tokens itself (the model's own tokenizer from the pinned revision; count parity is checked against `prompt_eval_count`). It compacts at 75% of budget during idle time. At 90% it compacts synchronously, with a visible "toparlıyorum" status (rare). Requests are never sent over budget |
| 6. Can cache misses be detected? | Yes, indirectly. Ollama responses report `prompt_eval_count` and `prompt_eval_duration`. A hit evaluates roughly the new tokens only; a miss evaluates roughly the whole prompt | Per-turn metric `cache_reuse_ratio = 1 − prompt_eval_count / prompt_tokens`, logged and shown in the diagnostics panel. Sustained misses raise a warning. The exact semantics of `prompt_eval_count` on each runner are verified in SPK-03 |
| 7. How is performance measured? | Benchmark B3 ([BENCHMARK_PLAN.md](BENCHMARK_PLAN.md)): 20-turn append-only growth, a mid-prefix change, compaction plus pre-warm, think on/off, and after a model reload, on each runner path | Gate **G4**: reuse ratio ≥ 0.9 on ≥ 95% of append-only turns. If the primary engine fails G4, the same model is tested through `mlx_lm.server` or `llama-server` before the model is judged |

### 2.2 Ollama operating parameters (initial; finalized by P2 measurements)

| Setting | Value | Why |
|---|---|---|
| `OLLAMA_NO_CLOUD` | `1` | Disables remote inference and web search (verified in local `--help`) |
| `OLLAMA_HOST` | `127.0.0.1:11434` | Loopback only |
| `num_ctx` | **one constant for every request type** (initially 16384) | Changing `num_ctx` between requests can force a model reload in Ollama, so chat, extraction, research reading and compaction must all use the same value. The memory cost is measured at this size (G1) |
| `OLLAMA_NUM_PARALLEL` | `1` (baseline) **or** `2`, decided by benchmark B3e | With one slot, a background request between user turns can **overwrite the conversation's cached prefix**, so the next user turn pays a cold prefill. Two slots isolate background work at a small KV cost on hybrid models. The scheduler still prevents concurrent execution ([MEMORY_ARCHITECTURE.md §16.3](MEMORY_ARCHITECTURE.md)). The alternative is to re-warm the conversation prefix during idle after each background job |
| `OLLAMA_MAX_LOADED_MODELS` | `2` | Primary LLM + embedding model co-resident |
| `keep_alive` | `-1` for the primary LLM; e.g. `30m` for the embedding model | Avoid cold loads during a session |
| `think` | `false` for voice, extraction and research reading; per StylePlan for text | Latency and clean JSON |
| Sampling | Model-card recommendations as the starting point (Qwen3.5 non-thinking: temperature 0.7, top_p 0.8, top_k 20, presence_penalty 1.5); `temperature 0` for extraction and classification | Presence penalty tuned in P2 (the card warns that high values can cause language mixing) |
| Version | Pinned; upgraded only after the provider contract suite and B2/B3 re-run | Rapid release cadence |

---

## 3. Embeddings and retrieval storage

| Option | Notes | Verdict |
|---|---|---|
| **Qwen3-Embedding-0.6B** | Strong multilingual retrieval for its size; instruction-aware queries; MRL dimensions; ~0.6–1.2 GB | **Provisional default** |
| EmbeddingGemma-2 (270M text) | 768d with MRL (512/256/128); MTEB-multilingual-v2 61.36 (vendor); runs on Ollama MLX; ~0.35 GB | Lightweight alternative / low-power profile |
| BGE-M3 | 1024d, multilingual, older | Bake-off reference |

**Decision procedure (P2, SPK-06):** build a Turkish retrieval set (≈300 query→memory pairs from the fictional eval personas, including diacritic-less queries and inflected names). Measure recall@10 and nDCG@10 at the full and truncated dimensions, plus latency, then pick the smallest model and dimension within 2 points of the best.

**Vector store — Decision: `sqlite-vec` v0.1.9 (stable), brute-force KNN.** At personal scale (≤ 100k memories × 768–1024 dims), exact search is a few to tens of milliseconds and needs no index tuning. The ANN indexes (DiskANN, IVF) in the 0.1.10 alphas are not needed and not adopted. sqlite-vec is pre-1.0, so the version is pinned, the vector schema is isolated in its own tables, and re-indexing is cheap: everything can be rebuilt from `memories`.

**Rejected:** Chroma, LanceDB, Qdrant, pgvector. Each adds infrastructure without a requirement that SQLite cannot meet. FAISS adds nothing at this scale.

**Full text — Decision: SQLite FTS5** over pre-normalized columns (Turkish casefold, diacritic-folded and stemmed variants; see [MEMORY_ARCHITECTURE.md §6](MEMORY_ARCHITECTURE.md)). A trigram FTS table is used for fuzzy name matching.

**Knowledge graph — Decision: relational tables in the same SQLite DB** plus recursive CTEs for traversal. Rejected: Neo4j and other graph servers (infrastructure); embedded graph DBs (another storage engine to back up, migrate and secure for a graph of a few thousand nodes).

---

## 4. Backend platform

| Concern | Decision | Alternatives / notes |
|---|---|---|
| Language | **Python 3.13** (pinned via `uv`; re-check 3.14 wheel coverage for `mlx`, `onnxruntime`, `sqlcipher3` at P1 start) | Rust (axum): weaker local-AI ecosystem. Node: weaker. |
| Env and packaging | **uv** (lockfile, Python management) | Poetry: slower, no Python management |
| Web framework | **FastAPI** + uvicorn, Pydantic v2 | Litestar (fine, smaller ecosystem) |
| HTTP client | **httpx** (async, timeouts, used only by the egress gateway and the provider adapters) | aiohttp |
| SQLite driver | **Decision (SPK-04, ADR-0003): `sqlcipher3` 0.6.4** (DB-API 2, same interface as `sqlite3`), imported only by `storage/driver.py`. The uv-managed stdlib `sqlite3` can also load extensions, but it cannot encrypt, so it is never used for data | `apsw`: not needed |
| Encryption | **Decision (SPK-05 passed, ADR-0003): SQLCipher 4.19.0 community** (SQLite 3.53.4, bundled OpenSSL 3.6.0 in the official `sqlcipher3` wheel), raw 256-bit key from the Keychain via the Rust shell; sqlite-vec 0.1.9 and FTS5 work under it; encrypted by default ([SECURITY_MODEL.md §5.1](SECURITY_MODEL.md)) | Field-level encryption: breaks search |
| Migrations | **Custom forward-only SQL runner** (numbered files, checksums, `schema_migrations` table, pre-migration backup) | Alembic/SQLAlchemy: heavy, and the virtual tables are raw SQL anyway |
| Typing / lint | pyright (strict) or mypy `--strict`, ruff, `import-linter` for module contracts | |
| Tests | pytest, pytest-asyncio, hypothesis | |
| Config | TOML + Pydantic v2 models with a small custom loader (TOML → `LAZIS_*` env → overrides) | pydantic-settings: not needed for three layers; the custom loader also controls error messages (no values leaked) |
| Turkish NLP | own `text` module + **PyStemmer** (Snowball Turkish), `rapidfuzz` (Jaro-Winkler) | Zemberek (JVM): too heavy. Full morphological analysis deferred. |

---

## 5. Desktop and UI

| Concern | Decision | Notes |
|---|---|---|
| Shell | **Tauri 2.12.x** (stable). Tauri 3 is alpha-only, so we do not adopt it. | Electron rejected: bundled Chromium costs hundreds of MB of RAM on a memory-constrained machine. Native SwiftUI rejected: slower UI iteration; Three.js is the requirement. |
| WebView | WKWebView (system WebKit) | WebGL2 baseline; WebGPU (Three.js `WebGPURenderer`) evaluated later |
| Framework | **Vue 3** + **TypeScript (strict)** + Vite + Pinia + vue-i18n | |
| 3D | **Three.js** (exact version pinned) with custom GLSL shaders, used directly | TresJS rejected: an abstraction layer over a render loop we need to control precisely |
| API types | OpenAPI → `openapi-typescript`; WS events JSON Schema → TS | |
| UI tests | Vitest (units), **Playwright WebKit** against the dev server | `tauri-driver` WebDriver is not available for macOS WKWebView, so the full Tauri app is smoke-tested manually with a scripted checklist |

---

## 6. Voice stack

### 6.1 Speech recognition (Turkish)

| Option | Turkish | Notes | Verdict |
|---|---|---|---|
| **Whisper large-v3-turbo** (via `mlx-whisper`, or whisper.cpp with Metal/CoreML) | Official | Robust, MIT. One secondary source reports turbo 2–4 pp worse WER than large-v3 for Turkish (unverified) | **Provisional primary** |
| Whisper large-v3 | Official | Slower, more accurate | Bake-off |
| `selimc/whisper-large-v3-turbo-turkish` | Community fine-tune (WER 18.9 on its CV17 eval) | Check license and robustness | Bake-off |
| Qwen3-ASR 1.7B / 0.6B | Turkish in its 30-language list | One anecdotal Turkish test showed errors on numbers and codes | Bake-off |
| Parakeet TDT v3, Voxtral Mini, Canary | No Turkish | — | Rejected |

Whisper hallucinates on silence, so VAD gating is mandatory. A domain prompt (`initial_prompt`) seeded with the user's frequent names and terms from the knowledge graph improves recognition of proper nouns. The STT choice is made by the P13 test suite: fast, quiet, noisy and informal speech, proper names, interrupted and long utterances ([BENCHMARK_PLAN.md §7.2](BENCHMARK_PLAN.md)). Runtimes (mlx-whisper vs. whisper.cpp + CoreML) are compared on the same weights.

### 6.2 Voice activity and end-of-turn

- **Silero VAD v6.2** (ONNX, 16 kHz): **Decision.**
- **Smart Turn v3.2** (pipecat-ai): audio-based semantic end-of-turn detection, 23 languages including **Turkish** (Turkish was the top-accuracy language in the v3 release table, 97.1% on 966 samples). Runs in about 10–20 ms on CPU. **Decision**, with a silence-timeout fallback.

### 6.3 Speech synthesis (Turkish, natural male voice)

Turkish support was verified against model cards, not assumed:

| Option | Turkish? | License | Voice | Fit on M4 Pro | Verdict |
|---|---|---|---|---|---|
| **Chatterbox Multilingual V3** (Resemble AI, 0.5B) | **Yes** (official, 23 languages) | MIT (outputs carry the Perth imperceptible watermark) | Zero-shot clone from a reference clip → choose a male reference | MLX port (fp16 bundle 1.3 GB via mlx-audio); RTF on M4 not published — **VERIFY**. The English-only Chatterbox-Flash shows RTF 0.78 on M4 (MLX); this is *not* evidence for the multilingual model | **Leading candidate — not final**; chosen only by the P13 listening and latency tests |
| Coqui XTTS-v2 | Yes (official, 17 languages) | CPML (non-commercial) | Zero-shot clone | PyTorch; MPS support is uneven; Coqui shut down, the community fork is maintained | Bake-off candidate (personal use OK) |
| VoxCPM2 (OpenBMB, 2B) | Yes (30 languages) | Apache 2.0 | Clone **and text-described voice design**; 48 kHz output; streaming API | ~8 GB VRAM bf16 and RTF 0.30 on an RTX 4090 (model card). Real-time use on the M4 Pro is doubtful *(est.)*, but this is **measured, not assumed** | Bake-off candidate **and** offline voice-design tool |
| Trendyol-TTS (VoxCPM2 + Turkish LoRA) | Turkish-focused | MIT metadata (check upstream) | Not documented | as VoxCPM2 | Bake-off candidate (Turkish prosody reference) |
| OmniVoice (k2-fsa) | 600+ languages claimed; **Turkish not confirmed** | check | Zero-shot clone | unknown | Include only if Turkish is confirmed at test time |
| Piper `tr_TR-dfki` | Yes | Voice-dataset license; Piper runtime now GPL fork | Fixed voice — **VERIFY gender** | CPU, very fast | **Emergency fallback** |
| Supertonic 3 | Listed (`tr`) | OpenRAIL-M; repo archived | Preset voices | ONNX, on-device fast | Fallback candidate (maintenance risk) |
| MMS-TTS `tur` | Yes | CC-BY-NC 4.0 | Single speaker | Fast VITS | Fallback candidate |
| Kokoro, Qwen3-TTS, Voxtral TTS | **No Turkish** | — | — | — | Rejected |
| Fish Audio S2 Pro | Turkish in long-tail list only | Unclear / non-commercial mirror gate | — | Heavy | Rejected for now |

**Language support is necessary, not sufficient.** The TTS engine is selected only by the P13 evaluation suite ([BENCHMARK_PLAN.md §7](BENCHMARK_PLAN.md)): pronunciation, naturalness, male-voice suitability, expressiveness, stability, latency, resources, streaming and licensing, all with blind listening by the user. A short feasibility smoke test in P2 (SPK-07) measures memory and real-time factor only. No quality decision is made there.

**Voice identity plan:** do not clone a real person without consent. Target voice profile: **male, slightly deep, warm, natural, expressive, comfortable for long listening, clear Turkish diction**. Use VoxCPM2 voice design ("otuzlu yaşlarda, hafif tok, sıcak ve sakin bir erkek sesi; net İstanbul Türkçesi") to generate synthetic reference candidates. The user then picks one in a listening test, and it is used as the reference for whichever engine wins. Alternatively, the user can record a consenting speaker. Decided in P13.

### 6.4 Audio I/O and echo cancellation

**Decision: `lazis-audio`, a small Swift helper using `AVAudioEngine` with voice processing enabled (VPIO).** Capture and playback share the same voice-processing I/O unit, so macOS gets the correct echo reference. It also provides noise suppression and AGC. PCM is exchanged with `lazis-core` over a Unix domain socket.
Known constraints from Apple's guidance and developer reports: voice processing must be configured before the engine starts, and AEC needs a short convergence period, so barge-in is suppressed for the first ~300 ms of playback. A headphone mode bypasses AEC.
**Alternatives evaluated in the P13 spike (SPK-09):** WebRTC APM (Python bindings) with PortAudio; LocalVQE AEC; and the `soniqo/speech-swift` toolkit (Apache 2.0; Whisper, Qwen3-ASR, Chatterbox, Silero, Smart Turn, AEC on MLX/CoreML), a possible all-Swift voice sidecar whose Turkish coverage needs verification.

---

## 7. Research stack

| Concern | Decision |
|---|---|
| Search | **Docker-free and provider-agnostic** (owner requirement, Phase 1 brief): pluggable Python `SearchProvider` adapters. Defaults: **Wikipedia** API (tr + en) for reference queries and **`ddgs`** as the no-key web search (scraping-based, fragile, isolated behind the port); optional user-supplied free-tier key providers (never required); optional **SearXNG installed natively** in its own virtualenv (never Docker, never required). The Phase 0 recommendation "SearXNG in Docker" is **withdrawn** |
| Fetch | httpx through the egress gateway: timeouts, size caps, content-type allowlist, no cookies, no JS |
| Extraction | **trafilatura** (main-content extraction + metadata) |
| JS-heavy pages | Deferred (Playwright is heavy); skip and report |
| Permission engine | Built in (`research.permissions`): modes, query classes, ordered rules; no external dependency ([RESEARCH_ARCHITECTURE.md §1](RESEARCH_ARCHITECTURE.md)) |

### 7.1 Local document ingestion stack (P11)

| Concern | Decision | License |
|---|---|---|
| PDF text layer | **pypdf**, fallback **pdfminer.six** (PyMuPDF rejected: AGPL) | BSD-3 / MIT |
| Markdown + frontmatter | **markdown-it-py** + PyYAML `safe_load` | MIT / MIT |
| Saved HTML | **trafilatura** | Apache-2.0 |
| File watching | **watchdog** (FSEvents backend on macOS) + periodic reconcile | Apache-2.0 |
| Parser isolation | Separate worker process with resource limits (stdlib `multiprocessing` + `resource`) | — |
| OCR | Not in v1 (a macOS Vision-based helper is possible later) | — |

---

## 8. Hardware feasibility analysis

### 8.1 Unified memory budget (target machine, 24 GB)

| Component | Text mode | Voice mode | Notes |
|---|---|---|---|
| macOS + user's other apps | 6–9 GB | 6–9 GB | Variable; browsers and IDEs dominate |
| Primary LLM (Qwen3.5-9B Q4, constant 16K `num_ctx`) | ~7.5–8 GB | ~7.5–8 GB | weights 6.6 GB + KV ≈ 0.5 GB + compute buffers *(est.)*; one context size for all modes (§2.2) |
| *(alt.) Gemma 4 12B QAT* | *~9–10 GB* | *~9 GB* | |
| Embedding model (Qwen3-Embedding-0.6B / EmbeddingGemma-2) | 0.4–1.2 GB | 0.4–1.2 GB | can be unloaded after idle |
| STT (Whisper large-v3-turbo, MLX) | — | 1.0–1.7 GB | fp16 ~1.6 GB; quantized smaller |
| TTS (Chatterbox Multilingual, MLX fp16) | — | 1.5–2.0 GB | |
| VAD + Smart Turn | — | < 0.1 GB | |
| lazis-core (Python, SQLite caches) | 0.4–0.6 GB | 0.5–0.8 GB | |
| Tauri / WKWebView + Three.js | 0.3–0.5 GB | 0.3–0.5 GB | |
| **LAZIS total** | **≈ 9–10 GB** | **≈ 11.5–14 GB** | The upper end touches the 14 GB budget, so it is measured by G1/B10; the embedding model can be evicted during voice sessions if needed. Gemma 4 12B adds ~1.5–2 GB |
| **Headroom** | ≈ 5–9 GB | ≈ 2–6 GB | Feasible; a 27B model is **not** |

The GPU working set (LLM + STT + TTS ≈ 10–11 GB) fits inside macOS's default wired limit for a 24 GB machine. We do not plan to raise `iogpu.wired_limit_mb`.

### 8.2 Throughput estimates (M4 Pro: 273 GB/s memory bandwidth)

Decode is memory-bound: tok/s ≈ efficiency (0.6–0.75) × 273 GB/s ÷ bytes read per token.

| Model (4-bit) | Weights read/token | Decode *(est.)* | Prefill *(est.)* |
|---|---|---|---|
| Qwen3.5-9B | ~5.2 GB | 30–40 tok/s (more with MTP) | 350–700 tok/s |
| Gemma 4 12B | ~6.7 GB | 25–31 tok/s | 280–550 tok/s |
| Qwen3-14B | ~8.4 GB | 19–24 tok/s | 220–400 tok/s |
| Qwen3-8B | ~4.7 GB | 35–43 tok/s | 400–750 tok/s |

Turkish speech runs at about 2–2.5 words/s, or about 5–7 tokens/s of text. Any candidate's decode speed is therefore ample for voice. **The latency bottleneck is prefill**: a cold 3,000-token prompt costs about 4–9 s. The append-only, cache-friendly prompt layout ([ARCHITECTURE.md §6](ARCHITECTURE.md)) is therefore a hard design requirement, not an optimization.

### 8.3 Voice latency budget (end of user speech → first audio)

**None of these numbers are measured.** They are planning budgets used to size the design. Each stage is measured separately in P13 ([BENCHMARK_PLAN.md §7.5](BENCHMARK_PLAN.md)), and no end-to-end figure is presented as verified before then.

| Stage | Budget *(est.)* | Measured by | Optimization |
|---|---|---|---|
| 1. Speech endpoint detection (last speech frame → turn committed) | 250–400 ms | `t_speech_end → t_turn_commit` | Smart Turn at 200 ms silence instead of an 800 ms timeout |
| 2. STT processing (5 s utterance) | 250–500 ms (partly hidden by speculative STT) | `t_turn_commit → t_stt_done` | turbo model, warm, GPU |
| 3a. Retrieval + prompt assembly | 50–100 ms | `t_stt_done → t_request_sent` | voice budget ≤ 500 memory tokens |
| 3b. LLM time-to-first-token (prefill of ≈ 300–600 new tokens) | 400–1,200 ms | `t_request_sent → t_first_token` | warm prefix (G4), `think=false` |
| 3c. First clause generation (≈ 12–20 tokens) | 300–600 ms | `t_first_token → t_first_clause` | clause-level chunking |
| 4. TTS time-to-first-audio (first clause synthesized) | 200–600 ms | `t_first_clause → t_first_pcm` | streaming or small first chunk, warm model |
| 5. Audio playback startup (PCM handed over → audible) | 20–80 ms | `t_first_pcm → t_playback_started` (from `PLAY_MARK`) | pre-started engine, small buffers |
| **Sum** | **≈ 1.5–3.5 s** | | Targets p50 ≤ 1.8 s, p95 ≤ 3.0 s †, to be confirmed or revised by ADR after P13 measurement |

### 8.4 Thermals, battery, disk
- Sustained GPU inference on battery drains it quickly. Power profiles (P15): *Battery* = Qwen3.5-4B or a smaller context, a 30 fps cap, deferred background learning.
- Disk: about 30–40 GB for the bake-off model set, then about 12 GB steady state.

---

## 9. Licensing summary (personal use)

Apache 2.0: Qwen3.5, Gemma 4, VoxCPM2, trafilatura, watchdog · MIT: Chatterbox, Whisper, Silero VAD, sqlite-vec (MIT/Apache), Tauri (MIT/Apache), Vue, Three.js, pdfminer.six, markdown-it-py · BSD-style: SQLCipher community edition, pypdf · **Non-commercial**: XTTS-v2 (CPML), MMS-TTS (CC-BY-NC) · AGPL: SearXNG (separate process, self-hosted, unmodified, so no obligation is triggered); PyMuPDF rejected for that reason. If LAZIS is ever distributed, the non-commercial options must be removed. License rules for new dependencies: [ENGINEERING_STANDARDS.md §8](ENGINEERING_STANDARDS.md).

---

## 10. Scheduled verification spikes

Spike IDs are phase-independent (Phase 0's `S1-x`/`S8-x` IDs are retired). Protocols are in [BENCHMARK_PLAN.md](BENCHMARK_PLAN.md).

| ID | Phase | Question | Method | Blocks |
|---|---|---|---|---|
| SPK-04 | P1 | Do sqlite-vec + FTS5 load with uv-managed CPython 3.13 (`enable_load_extension`), or is `apsw` needed? | smoke test | storage driver ADR — **done 2026-10-17: yes (stdlib and sqlcipher3); `apsw` not needed** |
| SPK-05 | P1 | SQLCipher + sqlite-vec + FTS5 compatibility; KNN/FTS performance on an encrypted 50k DB; page-cache sizing; Keychain item creation and access path | smoke + perf test | encryption-by-default ADR — **done 2026-10-17: passed, see ADR-0003** |
| SPK-01 | P2 | Turkish quality, tools and JSON across Qwen3.5-9B / Gemma 4 12B / Qwen3-14B / Qwen3-8B | bake-off B1–B8 | primary model ADR |
| SPK-02 | P2 | Is JSON-schema `format` grammar-enforced on each Ollama runner, or only validated? | schema-violation stress test | extraction design |
| SPK-03 | P2 | Prefix-cache reuse for append-only prompts per runner; tokenization round-trip drift (03b); compaction pre-warm; `prompt_eval_count` semantics | B3 | prompt layout, gate G4 |
| SPK-06 | P2 | Embedding model bake-off (Turkish retrieval, plain and diacritic-less) | B9 | memory indexing ADR |
| SPK-07 | P2 | Voice feasibility smoke: memory co-residency of LLM + Whisper turbo + a TTS candidate; RTF on 5 Turkish sentences (no quality decision) | B10 | memory budget for the LLM choice |
| SPK-08 | P2 | Which runner (MLX vs. llama.cpp) serves each tag; cold-load time per tag | B1 + debug logs | tag choice |
| SPK-13 | P11 | Turkish PDF/Markdown extraction quality and ingestion throughput | fixtures + synthetic folder | ingestion parameters |
| SPK-09 | P13 | VPIO helper AEC quality with built-in MacBook speakers; barge-in false-trigger rate | synthetic echo harness | voice I/O decision |
| SPK-10 | P13 | STT bake-off (Turkish categories, the user's own recordings) | V1 | STT choice |
| SPK-11 | P13 | TTS bake-off + voice identity selection | V2 (blind listening) | TTS choice |

## 11. References (accessed 2026-10-17)

- Qwen releases and timeline: https://github.com/QwenLM/Qwen3.8 · Qwen3.5-9B card: https://huggingface.co/Qwen/Qwen3.5-9B · Qwen3.6-27B card: https://huggingface.co/Qwen/Qwen3.6-27B · Qwen3.8-27B card: https://huggingface.co/Qwen/Qwen3.8-27B
- Qwen3.5 small models analysis: https://artificialanalysis.ai/articles/qwen3-5-small-models
- Gemma 4 model card: https://ai.google.dev/gemma/docs/core/model_card_4 · Gemma releases: https://ai.google.dev/gemma/docs/releases · Gemma (Wikipedia): https://en.wikipedia.org/wiki/Gemma_(language_model) · vLLM Gemma 4 12B recipe: https://recipes.vllm.ai/Google/gemma-4-12B-it
- Ollama blog: https://ollama.com/blog · releases: https://github.com/ollama/ollama/releases · v0.40 MLX default: https://modelfit.io/blog/ollama-0-40-0-mlx-default-apple-silicon/ · library: https://ollama.com/library/qwen3.5/tags, https://ollama.com/library/gemma4/tags, https://ollama.com/library/qwen3.8/tags, https://ollama.com/library/embeddinggemma-2
- Turkish evaluation context: https://arxiv.org/abs/2609.28007 · TurkBench: https://arxiv.org/html/2601.07020v1 · TurkishMMLU: https://arxiv.org/pdf/2407.12402
- sqlite-vec releases: https://github.com/asg017/sqlite-vec/releases
- Tauri releases: https://github.com/tauri-apps/tauri/releases
- Chatterbox: https://huggingface.co/ResembleAI/chatterbox · Chatterbox-Flash: https://huggingface.co/ResembleAI/chatterbox-flash · MLX port: https://huggingface.co/aufklarer/Chatterbox-Multilingual-MLX-fp16
- Turkish TTS survey: https://www.ablt.dev/blog/turkish-tts/ · VoxCPM2: https://huggingface.co/openbmb/VoxCPM2 · Trendyol-TTS: https://huggingface.co/Trendyol/Trendyol-TTS · Supertonic 3: https://huggingface.co/Supertone/supertonic-3 · Piper voices: https://huggingface.co/rhasspy/piper-voices
- Qwen3-TTS languages: https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice · Voxtral TTS: https://www.marktechpost.com/2026/03/28/mistral-ai-releases-voxtral-tts-a-4b-open-weight-streaming-speech-model-for-low-latency-multilingual-voice-generation/
- Whisper Turkish fine-tune: https://huggingface.co/selimc/whisper-large-v3-turbo-turkish · Whisper v3 vs turbo: https://vexascribe.com/whisper-large-v3-vs-turbo · Qwen3-ASR: https://www.baseten.co/library/qwen-3-asr-1-7b/
- Silero VAD: https://github.com/snakers4/silero-vad/releases · Smart Turn: https://github.com/pipecat-ai/smart-turn, https://www.daily.co/blog/announcing-smart-turn-v3-with-cpu-inference-in-just-12ms/
- Apple voice processing (WWDC19 session 510): https://developer.apple.com/videos/play/wwdc2019/510/ · AEC convergence thread: https://developer.apple.com/forums/thread/829784 · speech-swift: https://github.com/soniqo/speech-swift
- Embeddings: Qwen3 Embedding paper https://arxiv.org/abs/2506.05176 · EmbeddingGemma: https://deepmind.google/models/gemma/embeddinggemma/

## 12. Phase 1 stack as built (2026-10-17)

Exact versions are locked in `core/uv.lock`, `apps/desktop/pnpm-lock.yaml` and `apps/desktop/src-tauri/Cargo.lock`.

| Layer | Components (resolved versions) |
|---|---|
| Backend | CPython 3.13.16 (uv 0.13.1) · FastAPI 0.143.3 · uvicorn 0.54.0 · Pydantic 2.14.1 · sqlcipher3 0.6.4 (SQLCipher 4.19.0, SQLite 3.53.4) |
| Backend dev | pytest 9.1.1 · httpx (TestClient) · ruff 0.17.1 · pyright 1.1.414 (strict) · import-linter 2.15 · pip-audit 2.10.1 · sqlite-vec 0.1.9 (spike group only) |
| Shell | Rust 1.99.1 (edition 2024, MSRV 1.90) · Tauri 2.12.4 · tauri-plugin-single-instance 2.5.4 · tauri-plugin-log 2.10.1 · security-framework 3.7.0 (Keychain, `SecRandomCopyBytes`) · sha2 0.10 · zeroize 1.9 · libc 0.2 |
| UI | Node 24.10 · pnpm 10.28.2 · Vue 3.5.44 · Pinia 4.1.0 · vue-i18n 11.4.14 · @tauri-apps/api 2.12.4 · TypeScript 5.9.3 · Vite 8.3.4 · Vitest 5.0.5 · happy-dom 21.0.3 · vue-tsc 3.3.13 · openapi-typescript 7.13.0 |
| Task runner | GNU make (ships with the Command Line Tools); the planned `just` was not adopted to avoid an extra tool |

Not used in P1: httpx at runtime (no outbound HTTP), Ollama, any model, Playwright (P4), Three.js (P14), Docker (never).
