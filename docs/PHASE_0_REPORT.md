# LAZIS — Phase 0 Final Report

> ⚠️ **Historical document.** It was revised by Phase 0.1. The current, authoritative summary is [PHASE_0_FINAL_REVIEW.md](PHASE_0_FINAL_REVIEW.md) (Turkish). Superseded here:
> - §J roadmap (11 phases → 15 phases);
> - §E and §L.4 learning defaults ("review everything" → risk-based A/B/C policy with an optional review mode);
> - §G and §L.9 research defaults ("ask each query" → permission modes with automatic public search);
> - §L.3 encryption timing (SQLCipher by default from P1);
> - §C runner wording (the default `qwen3.5:9b` tag is GGUF; the runner is verified in P2);
> - spike IDs (`S1-x`/`S8-x` → `SPK-xx`).
>
> The rest remains valid as the Phase 0 record.

> Date: 2026-10-17 · Phase: 0 (research and blueprint) · Status: superseded by Phase 0.1
> No application code was written in Phase 0. No models were downloaded and no benchmarks were run: all performance figures are labeled as estimates and are scheduled for measurement in Phase 1.

---

## A. Architecture summary

LAZIS is a **modular monolith** (`lazis-core`, Python 3.13) surrounded by a few processes, each with a concrete technical reason to be separate:

- **LAZIS Desktop**: Tauri 2 (thin Rust shell) + Vue 3/TypeScript UI + Three.js Neural Core.
- **Ollama 0.40.x**: local LLM and embedding server, using the MLX runtime on Apple Silicon. Accessed only through a provider abstraction and run with cloud features disabled.
- **lazis-audio**: a small Swift helper for real-time audio with macOS Voice-Processing I/O echo cancellation (Phase 8).
- **SearXNG**: an optional Docker container for private research (Phase 9).

All personal data lives in one SQLite database (with FTS5 and sqlite-vec), plus a disposable cache DB. Domain modules (conversation, personality, memory, graph, learning, bootstrap, research, voice) depend only on ports. Concrete engines are swappable by configuration. Key design commitments:
- an **append-only, cache-friendly prompt layout** (prefill is the latency bottleneck on Apple Silicon);
- **evidence-verified learning**;
- **name-only identity is never enough**;
- **research never writes memory**;
- **a single egress gateway**.

→ [ARCHITECTURE.md](ARCHITECTURE.md)

## B. Technology recommendations and alternatives

| Area | Recommendation | Main alternatives (status) |
|---|---|---|
| Backend | Python 3.13 + FastAPI + Pydantic v2, `uv` | Rust/axum (rejected: AI ecosystem), Node (rejected) |
| Inference engine | **Ollama 0.40.x** (MLX default on Apple Silicon; GGUF fallback) | mlx-lm server, llama.cpp `llama-server` (ready alternatives through `OpenAICompatLLMProvider`); LM Studio (not a dependency) |
| Storage | **SQLite** (WAL) + **FTS5** + **sqlite-vec 0.1.9** (exact KNN) | Chroma/LanceDB/Qdrant/Neo4j (rejected: unnecessary infrastructure) |
| Encryption | **SQLCipher** + Keychain key (pending spike S1-5) | FileVault only (minimum baseline) |
| Embeddings | Qwen3-Embedding-0.6B (provisional) | EmbeddingGemma-2 270M (light), BGE-M3 |
| Desktop | **Tauri 2.12** + Vue 3 + TS strict + Pinia + Three.js (WebGL2) | Electron (rejected: RAM), SwiftUI (rejected: iteration speed), Tauri 3 (alpha only) |
| STT | Whisper large-v3-turbo (MLX) (provisional) | Whisper large-v3, Turkish fine-tuned turbo, Qwen3-ASR |
| VAD / turn-taking | Silero VAD v6.2 + **Smart Turn v3.2** (Turkish supported) | silence timeout only (fallback) |
| TTS | **Chatterbox Multilingual V3** (MIT, Turkish official) (provisional) | XTTS-v2 (non-commercial), VoxCPM2 (offline voice design), Piper `tr_TR` / Supertonic 3 / MMS (fallbacks). Rejected: Kokoro, Qwen3-TTS and Voxtral TTS have no Turkish |
| Audio I/O | Swift helper with AVAudioEngine VPIO | WebRTC APM + PortAudio; speech-swift toolkit |
| Research | SearXNG (self-hosted) + ddgs + Wikipedia; trafilatura | user-supplied free-tier search keys (optional, never required) |

→ [TECHNOLOGY_DECISIONS.md](TECHNOLOGY_DECISIONS.md)

## C. Selected local AI models and reasons

**Primary (provisional): Qwen3.5-9B**, Q4-class (Ollama `qwen3.5:9b`, 6.6 GB).
- Its hybrid Gated-DeltaNet architecture keeps the KV cache at **32 KiB/token**, versus 144–160 KiB for the brief's Qwen3-8B/14B. That means 0.5 GiB at 16K context instead of 2.25–2.5 GiB, which is what makes voice + LLM + UI fit comfortably in 24 GB.
- It has the best documented multilingual results among models that fit (model card: MMMLU 81.2, MMLU-ProX 76.3, INCLUDE 75.6). Turkish-specific quality is **not** published and must be measured.
- Tool calling, thinking on/off, Apache 2.0, and support in Ollama's MLX runner.

**Challenger: Gemma 4 12B (QAT, 7.2 GB).** Strong multilingual family, native function calling, configurable thinking, and audio input (a future option). It costs about 1.5–2 GB more and decodes about 20–25% slower *(est.)*.

**Baselines kept for the bake-off:** Qwen3-14B and Qwen3-8B from the original brief.
**Rejected for this hardware:** all 26–35B models (Qwen3.5/3.6/3.8-27B, 35B-A3B MoEs, Gemma 4 26B/31B). At 16–22 GB they leave no room for the OS and voice.
**Selection method:** a Turkish, LAZIS-specific bake-off on this Mac covering naturalness (blind user ratings), instruction following, pushback, JSON-schema validity, extraction precision, tool calling, language drift, TTFT and memory, with hard gates. Benchmarks alone do not decide.

## D. Estimated hardware resource requirements *(estimates; measured in Phase 1/8)*

| Mode | LAZIS total memory | Headroom on 24 GB | Notes |
|---|---|---|---|
| Text | ≈ 9–10 GB | ≈ 5–9 GB | LLM ~7.5–8 GB + embeddings + core + UI |
| Voice | ≈ 11.5–13.5 GB | ≈ 2–6 GB | + Whisper turbo ~1–1.7 GB + Chatterbox ~1.5–2 GB |
| With Gemma 4 12B | + 1.5–2 GB | tighter | still feasible |

- Decode *(est.)*: Qwen3.5-9B 30–40 tok/s; Gemma 4 12B 25–31 tok/s; Qwen3-14B 19–24 tok/s. Turkish speech needs only about 5–7 tok/s.
- Prefill *(est.)* of 350–700 tok/s is the bottleneck, hence the cache-aware design.
- Voice latency budget: end of speech → first audio ≈ 1.5–3.4 s *(est.)*; targets p50 ≤ 1.8 s, p95 ≤ 3.0 s.
- Disk: ~30–40 GB for the bake-off set; ~12 GB steady state (121 GiB free now).
- Battery: sustained GPU use is costly, so power profiles are planned.

→ [TECHNOLOGY_DECISIONS.md §8](TECHNOLOGY_DECISIONS.md)

## E. Memory system design

- **Typed memories:** facts, preferences, events, episodes, relationship notes, projects, goals and dreams, and instructions to LAZIS. Each has a subject/predicate/object structure plus a canonical Turkish sentence. Each carries confidence, importance, sensitivity, trust rank, valid-time (with precision), observation time, version history and multiple sources with verbatim evidence.
- **Predicate registry** (config) drives duplicate and contradiction logic: supersede, coexist, or ask.
- **Write paths:** explicit commands (Turkish lexicon + tool calls), automatic extraction (evidence-verified; LAZIS's own words are never evidence), import, user edits, and hedged inferences (always pending).
- **Retrieval:** entity linking (aliases, kinship parser) + vector KNN + Turkish-aware FTS5 (casefolded, diacritic-folded and stemmed columns) + graph expansion, fused with RRF and scored by importance, confidence and recency. Packed to a token budget; sensitive items appear only when topically relevant. Target ≤ 80 ms p95.
- **Deletion:** complete across indexes and summaries, with optional evidence redaction, HMAC suppression against re-learning, an honest backup-retention notice, and per-person forget.
- **Backups:** daily, pre-migration and pre-import snapshots with rotation, integrity checks and tested restore.

→ [MEMORY_ARCHITECTURE.md](MEMORY_ARCHITECTURE.md) · [KNOWLEDGE_GRAPH_DESIGN.md](KNOWLEDGE_GRAPH_DESIGN.md)

## F. Voice system design

lazis-audio (Swift, AVAudioEngine with Voice Processing: AEC, NS, AGC) streams 16 kHz frames over a Unix socket to the voice module:
- **Silero VAD → Smart Turn v3.2** end-of-turn detection, with **speculative Whisper turbo STT** (proper-noun priming from the knowledge graph, hallucination filters).
- The conversation engine streams tokens to a **Turkish clause chunker** and **TTS text normalizer** (currency, dates, times, ordinals, abbreviations, pronunciation lexicon), then to **Chatterbox Multilingual** streaming synthesis, played back through the same VPIO unit.
- **Barge-in:** duck, then flush, with backchannel tolerance. Only the spoken portion is recorded.
- **Modes:** push-to-talk, hands-free session, and (later) a wake word. A headphone mode and a half-duplex fallback are available.
- **Voice identity:** a synthetic male voice designed offline with VoxCPM2 (or a consenting speaker), used as the reference for live synthesis.

→ [VOICE_ARCHITECTURE.md](VOICE_ARCHITECTURE.md)

## G. Research system design

- **Pipeline:** need detection, then query building with a **privacy scrubber** (removes all knowledge-graph names and identifiers), then **approval** (ask by default), then the single **egress gateway** (HTTPS, SSRF/DNS-rebinding guards, limits).
- **Sources and extraction:** SearXNG / ddgs / Wikipedia, then fetch, then trafilatura.
- **Verification:** a **quarantined reader** with no tools, returning claims plus verbatim quotes; quote verification and injection screening; cross-source scoring; a cited Turkish answer.
- **Caching and offline:** a TTL-classed cache, and an offline fallback with an explicit staleness caveat.
- **Isolation:** taint tracking disables write tools whenever web content is in context. Results never touch personal memory without explicit promotion.

→ [RESEARCH_ARCHITECTURE.md](RESEARCH_ARCHITECTURE.md)

## H. User interface design

- **Layout:** a Tauri window with a central Three.js **Neural Core**: a noise-displaced energy sphere with fresnel glow, neural filaments, instanced holographic rings with scanlines, a GPU-animated particle halo, and half-resolution bloom.
- **States:** IDLE blue, LISTENING purple (mic-reactive), THINKING yellow (with retrieving/researching/reasoning sub-states), SPEAKING green (TTS-envelope-reactive), ERROR red (no strobing). Transitions use spring-damped parameters and OKLab color interpolation.
- **Performance:** 60/30/0 fps scheduling, dynamic resolution, a low-power profile, and reduced-motion support.
- **Views:** Conversation (with memory chips and a "neden?" explainability panel), Memory, People graph, Inbox, Import (diff preview + rollback), Settings, System (latency and memory metrics), plus a persistent privacy HUD. The UI is in Turkish via vue-i18n.

→ [UI_ARCHITECTURE.md](UI_ARCHITECTURE.md) · [PERSONALITY_ENGINE.md](PERSONALITY_ENGINE.md) (personality layers)

## I. Security and privacy architecture

- **Storage:** local data with 0700/0600 permissions; FileVault check; optional SQLCipher with the Keychain key passed over stdin.
- **Local API:** loopback-only with a per-launch token and Origin checks. Ollama is restricted to loopback with `OLLAMA_NO_CLOUD=1`.
- **Network:** a single egress gateway with a kill switch (default offline) and an audit log.
- **Data classification:** normal, personal, sensitive (confirm before storing) and restricted (never stored; TC Kimlik, IBAN, card and password detectors).
- **Tool safety:** a tool registry with no shell or exec tools; taint tracking; a quarantined web reader.
- **Logs:** content-free by default.
- **Supply chain:** pinned dependencies and model hashes; no pickle files.
- **Third-party privacy:** sensitivity tiers apply to the people in the user's life, and per-person forget is one action.

→ [SECURITY_MODEL.md](SECURITY_MODEL.md)

## J. Implementation roadmap

| Phase | Focus | Size |
|---|---|---|
| 1 | Foundations (skeleton, config, storage + migrations, providers, eval and bench harness) and **model bake-off** | M |
| 2 | Conversation engine, streaming, append-only prompts, core persona, CLI | M |
| 3 | Memory core: schema, Turkish text utils, explicit commands, hybrid retrieval, deletion, backups | L |
| 4 | Desktop app (Tauri + Vue) and Neural Core, text mode, memory UI | L |
| 5 | Knowledge graph, entity resolution, kinship, merge/unmerge, **bootstrap import** | L |
| 6 | Continuous learning pipeline (evidence-verified extraction, contradictions, Inbox, idle scheduler) | L |
| 7 | Adaptive personality (style learning, follow-ups, anti-repetition, pushback) | M |
| 8 | Voice engine (VPIO helper, VAD + Smart Turn, STT, streaming TTS, barge-in, voice identity) | L |
| 9 | Research engine (egress, scrubber, quarantine, citations, cache) | M |
| 10 | Local knowledge sources and security hardening (SQLCipher everywhere, PathGuard) | M |
| 11 | Packaging, setup wizard, power profiles, upgrade playbooks, long soak | M |

Each phase ends with a gate review and requires your explicit approval. → [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md) · [ACCEPTANCE_CRITERIA.md](ACCEPTANCE_CRITERIA.md) · [TESTING_STRATEGY.md](TESTING_STRATEGY.md)

## K. Technical risks and mitigation strategies (top items)

| Risk | Score | Mitigation |
|---|---|---|
| Prefill latency makes turns slow | 16 | append-only prompts, idle compaction + pre-warm, small voice budgets, prefix-cache spike S1-3 |
| Turkish quality of 9–12B models | 15 | LAZIS-specific bake-off, Turkish few-shot persona, drift guard, Q4 vs Q8 comparison, upgrade path |
| Memory pollution (false memories) | 15 | evidence verification, thresholds, review-everything calibration period, provenance, undo |
| Turkish TTS naturalness/latency | 12 | multi-candidate bake-off, synthetic voice design, streaming, fallbacks |
| Entity-resolution errors | 12 | no name-only confirmation, tentative links, clarifications, reversible merges |
| Unified-memory pressure | 12 | single LLM, budgets, voice unload policy, power profiles |
| Prompt injection | 12 | quarantine, taint tracking, no dangerous tools, research never writes memory |
| Scope creep | 12 | phase gates, module contracts, ADRs |

→ Full register (22 risks): [RISK_ASSESSMENT.md](RISK_ASSESSMENT.md)

## L. Questions requiring your decisions

Recommended defaults are shown in **bold**. If you accept the defaults, I will proceed with them.

1. **Model priority:** within the latency gates, weight **Turkish naturalness over speed** (recommended), or the reverse?
2. **Phase 1 downloads:** may I pull the bake-off set (Qwen3.5-9B Q4 and Q8, Gemma 4 12B QAT, Qwen3-14B, Qwen3-8B, two embedding models; ≈ 30–40 GB) and run benchmarks **on AC power**?
3. **Encryption at rest:** enable **SQLCipher by default from Phase 3**, with the key in the Keychain plus a printed or password-manager recovery key (recommended), or rely on FileVault only?
4. **Learning mode at start:** **review-everything for the first 2–4 weeks** (you approve extracted facts in the Inbox), then auto-save high-confidence non-sensitive facts? Or auto-save from day one?
5. **Sensitive categories:** is the proposed list right (health, finances, beliefs, political views, sexual life, legal matters, ethnicity, memberships, biometrics, intimate relationship details)? Should any category be **never stored** rather than confirm-first?
6. **Address and tone:** **`sen`** (default) or `siz`? What name should LAZIS call you? Humor level: **light** / minimal / more playful?
7. **Voice setup:** do you mostly use **built-in speakers** or headphones? Default interaction: **push-to-talk with a hands-free session option** (recommended), or hands-free first? Do you want a wake word later?
8. **Voice identity:** **synthetic designed male voice** (recommended; no consent issues) or a recording of a consenting person (e.g., yourself)?
9. **Research defaults:** network **off until you enable it**; query approval **ask each time**; is running **SearXNG in Docker** acceptable (Docker is installed)?
10. **Runtime:** is **Python** (managed by `uv`, invisible in daily use) acceptable for the backend?
11. **Bootstrap:** will you write the **YAML file** (template provided in Phase 5), or do you prefer the guided interview first (Phase 7)?
12. **Usage scope:** **strictly personal, non-commercial** use? This allows non-commercial voice models as options.
13. **Source control:** **local git only** (recommended to start), or a private GitHub repository with macOS CI?
14. **Local sources (Phase 10):** which matter most: Markdown/Obsidian notes, Apple Notes export, PDFs, others?
15. **Locale:** confirm **Europe/Istanbul** timezone and Turkish UI as the defaults.

## M. Readiness assessment for Phase 1

**Verdict: ready to start Phase 1 once you approve the blueprint and answer the decisions in §L** (defaults are acceptable).

| Area | Confidence | Why |
|---|---|---|
| Architecture, storage, security model | High | Conventional, simple components; risks understood |
| Model choice | Medium | Strong candidates identified; Turkish quality and prefix-cache behavior are unmeasured (S1-1, S1-3) |
| Latency targets | Medium | Estimates are grounded in bandwidth math; must be measured on this Mac |
| Memory and KG quality | Medium | Design is conservative; quality depends on extraction evals (Phases 5–6) |
| Voice (TTS naturalness, AEC on built-in speakers) | Medium-low | Turkish-capable options verified on model cards, but no published M4 numbers; spikes S8-1…3 planned |
| UI / Neural Core | High | Well-understood WebGL techniques with explicit budgets |

**Prerequisites before Phase 1 work begins:**
1. Install `uv` (via Homebrew) and let it manage Python 3.13. The system Python 3.9.6 is unsuitable.
2. `git init` the repository (after your approval).
3. Configure Ollama's environment (`OLLAMA_NO_CLOUD=1`, loopback host). Ollama 0.40.4 is already installed.
4. Plug in AC power for the benchmark runs. The machine was on battery during the Phase 0 check.
5. About 40 GB of free disk for the bake-off model set (121 GiB available).

Already present and verified: Rust 1.99.1, Node 24.10, pnpm 10.28, Swift 6.4, Docker 28.4, Homebrew.

**Phase 1 will not start until you explicitly approve.**
