# LAZIS

A privacy-first, local-first, Turkish-speaking personal AI companion for Apple Silicon Macs. 

**Current phase:** Phase 9 (advanced automatic learning: whole lists, past / current / future, corrections in so many words, importance tiers, quality suggestions; [ADR-0020](docs/adr/0020-advanced-learning.md)) implemented and verified with the real model — **awaiting the owner's acceptance test and approval**. Phase 10 has not started. Model decision: [ADR-0001](docs/adr/0001-primary-model.md) (Accepted).

What runs today: a macOS desktop app (Tauri 2 + Vue 3, Turkish UI) that starts a local Python backend (FastAPI) over an authenticated loopback API, with a SQLCipher-encrypted database whose key lives in the macOS Keychain, plus a recovery-code flow. Phase 2 adds a local LLM through Ollama on loopback (primary: Gemma 4 12B; the backend's sandbox allows only Ollama's port, cloud inference disabled) Phase 3 adds one persistent Turkish assistant with a single continuous timeline ([ADR-0011](docs/adr/0011-single-assistant-timeline.md)), stored in the encrypted database: no conversation management, streaming, stop, recovery of interrupted replies, a token budget, evidence-checked compaction of long conversations, and cache pre-warming. Phase 4 makes it a desktop app to live with:

- an assistant state indicator driven by real events (Hazır / Düşünüyor / Yanıtlıyor / Sorun var);
- a menu-bar item;
- automatic restart of a crashed backend (bounded);
- Ollama reconnect and sleep/wake handling;
- a diagnostics panel without conversation content;
- safe Markdown replies with copy;
- a much lower idle cost.

Phase 5 gives LAZIS its character: a consistent, honest Turkish assistant that addresses the owner as "efendim" where it fits, disagrees when there is a reason, fits its length and tone to the message, and keeps that across restarts, sessions and summaries. Summaries (and later memory) reach the model as information, never as instructions.

Phase 6 adds personal memory: LAZIS learns lasting facts about the owner, people and projects from conversations (in the background, with the main model only), recalls the relevant ones in later conversations, asks when two people share a name, keeps old values as history, and forgets on request — all inside the encrypted database. Chat history and memory are separate layers.

Phase 7 adds a relationship graph between the owner, people, projects, places and organisations (who is whose sibling, who works where), answered from the graph. Phase 7.1 makes memory claims truthful: LAZIS never says it noted something unless the write was committed. Phase 7.2 keeps namesakes apart ("İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım"), asks "which one?" in chat, and makes "Lütfen şunu not al" reliable.

Phase 8 lets the owner hand LAZIS a prepared profile (Hafıza → Kişisel Bilgi Aktarımı). The file is read locally (Markdown and text by Gemma, section by section; JSON directly), compared with what LAZIS already knows, and shown in full: every fact, person and relationship with its source line, and every conflict with the stored value. Nothing is approved by default; nothing unapproved is written; the approved items are written in one transaction; an import can be undone from a previewed plan that keeps what was known before or confirmed since.

Phase 9 makes background learning more careful about *who*, *what* and *when*. A list is read in full ("Ahmet'in iki kardeşi var: Mehmet ve Ali"): when the model reads it in part, one focused re-read asks only about the missing names, and a count that differs from the names is kept as the user's words, nobody invented. The tense of the user's own words decides what is today's value, what is history ("eskiden", "Kervan'dan ayrıldım") and what is a plan ("gelecek yıl"); the time named is kept as written, never turned into a date. A different value without words that say it changed is asked about, not written over. "Hayır, Ahmet değil Mehmet demek istedim" corrects what the last message taught (asking when Mehmet could be several people). Repetition adds evidence but never certainty; importance tiers order recall and suggestions but never decide what is written; the memory screen shows read-only quality suggestions (duplicates, conflicts, stale facts, ambiguous people) that the owner acts on or hides. There is no voice or internet access yet.

## Quick start

```bash
make setup   # needs uv, pnpm (Node 24+), Rust stable, Xcode Command Line Tools
make dev     # run the desktop app (isolated "dev" profile)
make check   # all linters and automated tests
```

Details: [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md).

## Documentation

| Document | Contents |
|---|---|
| [PHASE_9_REPORT.md](docs/PHASE_9_REPORT.md) | **Start here.** Phase 9 report (Turkish): lists, time and currency, importance, repetition, sources, identity, conflicts and corrections, explicit saves, quality checks, chat performance, real-model results, tests, regressions, limits, acceptance steps |
| [adr/0020-advanced-learning.md](docs/adr/0020-advanced-learning.md) | ADR-0020: the refinement step (tense, change words, time phrase), whole lists without inventing anyone, salvage, repetition as evidence, computed importance, corrections, quality suggestions |
| [PHASE_8_REPORT.md](docs/PHASE_8_REPORT.md) | Phase 8 report (Turkish): personal knowledge import — architecture, file handling, Gemma extraction, identity, conflicts, preview, atomic write, undo, the six safety conditions, real-model tests, performance, regressions, limits, acceptance steps |
| [adr/0019-personal-knowledge-bootstrap.md](docs/adr/0019-personal-knowledge-bootstrap.md) | ADR-0019: the import pipeline, untrusted files, per-section extraction, people as proposals, no silent changes, one transaction, undo as a plan |
| [PHASE_7_2_REPORT.md](docs/PHASE_7_2_REPORT.md) | Phase 7.2 report (Turkish): namesakes, explicit save requests, internal labels |
| [PHASE_7_1_REPORT.md](docs/PHASE_7_1_REPORT.md) | Phase 7.1 report (Turkish): truthful memory claims |
| [PHASE_7_REPORT.md](docs/PHASE_7_REPORT.md) | Phase 7 report (Turkish): entity and relationship graph |
| [PHASE_6_REPORT.md](docs/PHASE_6_REPORT.md) | Phase 6 report (Turkish): memory architecture, database, extraction, people and projects, recall, privacy, performance, test results, known issues, acceptance steps |
| [PHASE_5_REPORT.md](docs/PHASE_5_REPORT.md) | Phase 5 report (Turkish): persona architecture, rules, prompt assembly, real-model evaluation A–G, continuity, performance, security, limits, verification steps, Phase 6 readiness |
| [PHASE_4_REPORT.md](docs/PHASE_4_REPORT.md) | Phase 4 report (Turkish): assistant states, diagnostics, recovery, menu bar, Markdown, measurements vs Phase 3, tests, security, known gaps, verification steps |
| [PHASE_3_REPORT.md](docs/PHASE_3_REPORT.md) |  Phase 3 report (Turkish): persistent conversations, schema, API, context management and compaction, cold-cache measurements, security, tests, known gaps, risks for Phase 4 |
| [adr/0011-single-assistant-timeline.md](docs/adr/0011-single-assistant-timeline.md) | ADR-0011: one assistant, one timeline, hidden technical sessions, data migration |
| [adr/0010-conversation-persistence-and-context.md](docs/adr/0010-conversation-persistence-and-context.md) | ADR-0010: conversation storage, turn lifecycle, prompt layout, token budget, compaction, pre-warming, deletion |
| [PHASE_2_REPORT.md](docs/PHASE_2_REPORT.md) | Phase 2 report (Turkish). Phase 2 report (Turkish): environment, model inventory and downloads, inference architecture, sandbox compatibility, chat, tests, model decision, Phase 3 readiness |
| [PHASE_2_MODEL_BENCHMARKS.md](docs/PHASE_2_MODEL_BENCHMARKS.md) | Phase 2 model benchmarks (Turkish): method, performance, memory, Turkish quality, extraction, MLX comparison |
| [adr/0001-primary-model.md](docs/adr/0001-primary-model.md) | ADR-0001 (Accepted): primary and fallback model, runtime, gate check, G2 revision record |
| [PHASE_1_1_REPORT.md](docs/PHASE_1_1_REPORT.md) | Phase 1.1 hardening report (Turkish): verified findings, network isolation, restore safety, recovery code, local API, tests, Phase 2 readiness |
| [PHASE_1_REPORT.md](docs/PHASE_1_REPORT.md) | Phase 1 report (Turkish, historical): what was built, how it was verified, measurements |
| [adr/0009-backend-network-sandbox.md](docs/adr/0009-backend-network-sandbox.md) | ADR-0009: OS-enforced network sandbox for the backend |
| [DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) | Setup, commands, process lifecycle, profiles, database, keys and recovery, API, troubleshooting |
| [adr/0003-storage-driver-and-encryption.md](docs/adr/0003-storage-driver-and-encryption.md) | ADR-0003: `sqlcipher3` driver, encryption by default, SPK-04/05 results |
| [PHASE_0_FINAL_REVIEW.md](docs/PHASE_0_FINAL_REVIEW.md) | Implementation readiness report (Turkish): changes, final architecture, roadmap, risks, decisions, Phase 1 readiness |
| [PROJECT_VISION.md](docs/PROJECT_VISION.md) | Vision, defining capability, pillars, principles, non-goals |
| [REQUIREMENTS.md](docs/REQUIREMENTS.md) | Functional and non-functional requirements (IDs, priorities, phases P1–P15) |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Processes, module map and dependency rules, data flows, cache-aware prompt layout, API contracts, state machine, errors, configuration, repository structure |
| [TECHNOLOGY_DECISIONS.md](docs/TECHNOLOGY_DECISIONS.md) | Model matrix, assumption review, engine comparison, context-caching analysis, voice/research/ingestion stacks, hardware feasibility, licensing, spikes, references |
| [BENCHMARK_PLAN.md](docs/BENCHMARK_PLAN.md) | Reproducible LLM, embedding and voice benchmarks with pass/fail gates and decision rules |
| [MEMORY_ARCHITECTURE.md](docs/MEMORY_ARCHITECTURE.md) | Memory model, risk-based learning policy (A/B/C), confidence and risk, lifecycle, confirmations, contradictions, corrections, review mode, rollback, retrieval, deletion, backups |
| [KNOWLEDGE_GRAPH_DESIGN.md](docs/KNOWLEDGE_GRAPH_DESIGN.md) | Entities, relationships, Turkish kinship and roles, entity resolution, relational questions, merge/unmerge/split, domains, bootstrap import |
| [LOCAL_INGESTION_ARCHITECTURE.md](docs/LOCAL_INGESTION_ARCHITECTURE.md) | Authorized local sources: classes, trust caps, pipeline, sync, revocation |
| [PERSONALITY_ENGINE.md](docs/PERSONALITY_ENGINE.md) | Five layers with precedence, persona, preferences, style selection, memory honesty, guards |
| [VOICE_ARCHITECTURE.md](docs/VOICE_ARCHITECTURE.md) | Audio I/O and AEC, turn-taking FSM, STT, streaming TTS, barge-in, voice identity, latency budget |
| [RESEARCH_ARCHITECTURE.md](docs/RESEARCH_ARCHITECTURE.md) | Permission modes, query classification, privacy scrubbing, providers, injection defenses, credibility, audit |
| [UI_ARCHITECTURE.md](docs/UI_ARCHITECTURE.md) | Early functional interface and final neural interface, views, rendering performance |
| [SECURITY_MODEL.md](docs/SECURITY_MODEL.md) | Threat model, trust classes, encryption and keys, tool permissions, audit logging |
| [ENGINEERING_STANDARDS.md](docs/ENGINEERING_STANDARDS.md) | Cross-phase coding, dependency, licensing, migration, API, logging and testing standards |
| [DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md) | 15 gated phases with objectives, prerequisites, scope, tests and exit conditions |
| [ACCEPTANCE_CRITERIA.md](docs/ACCEPTANCE_CRITERIA.md) | Measurable acceptance criteria per requirement |
| [TESTING_STRATEGY.md](docs/TESTING_STRATEGY.md) | Test pyramid, deterministic LLM testing, evaluation suites |
| [RISK_ASSESSMENT.md](docs/RISK_ASSESSMENT.md) | Risk register with scores and mitigations |
| [PHASE_0_REPORT.md](docs/PHASE_0_REPORT.md) | Historical Phase 0 report (partly superseded) |

## Target environment
MacBook Pro, Apple M4 Pro (14 CPU / 20 GPU cores), 24 GB unified memory, macOS 27. All AI inference is local. No cloud or paid APIs are required at runtime.
