# LAZIS

A privacy-first, local-first, Turkish-speaking personal AI companion for Apple Silicon Macs.

**Current phase:** Phase 3 (conversation engine: one persistent, encrypted assistant timeline with managed context; single-assistant addendum per ADR-0011) implemented and verified — **awaiting the owner's approval**. Phase 4 has not started. Model decision: [ADR-0001](docs/adr/0001-primary-model.md) (Accepted).

What runs today: a macOS desktop app (Tauri 2 + Vue 3, Turkish UI) that starts a local Python backend (FastAPI) over an authenticated loopback API, with a SQLCipher-encrypted database whose key lives in the macOS Keychain, plus a recovery-code flow. Phase 2 adds a local LLM through Ollama on loopback (primary: Gemma 4 12B; the backend's sandbox allows only Ollama's port, cloud inference disabled) Phase 3 adds one persistent Turkish assistant with a single continuous timeline ([ADR-0011](docs/adr/0011-single-assistant-timeline.md)), stored in the encrypted database: no conversation management, streaming, stop, recovery of interrupted replies, a token budget, evidence-checked compaction of long conversations, and cache pre-warming. There is no personal memory, voice or internet access yet — by design: chat history is not personal memory.

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
| [PHASE_3_REPORT.md](docs/PHASE_3_REPORT.md) | **Start here.** Phase 3 report (Turkish): persistent conversations, schema, API, context management and compaction, cold-cache measurements, security, tests, known gaps, risks for Phase 4 |
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
