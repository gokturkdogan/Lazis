# LAZIS

A privacy-first, local-first, Turkish-speaking personal AI companion for Apple Silicon Macs.

**Current phase:** Phase 0.1 complete (architecture revision and implementation readiness). No application code yet. Phase 1 starts only after explicit approval.

## Documentation

| Document | Contents |
|---|---|
| [PHASE_0_FINAL_REVIEW.md](docs/PHASE_0_FINAL_REVIEW.md) | **Start here.** Implementation readiness report (Turkish): changes, final architecture, roadmap, risks, decisions, Phase 1 readiness |
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
