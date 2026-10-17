# LAZIS — Requirements

> Status: Phase 0.1 (revised) · Last updated: 2026-10-17
> Priority: **M** = must, **S** = should, **C** = could. **Phase** = the roadmap phase that first delivers the requirement (P1–P15, see [DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md)).
> Measurable targets live in [ACCEPTANCE_CRITERIA.md](ACCEPTANCE_CRITERIA.md) and use the same IDs. Phase 0.1 added or changed IDs marked ★.

## 0. Defining capability

LAZIS's defining characteristic is a **continuously improving, structured understanding of its user**:
- who they are and their history;
- family, spouse and close relationships, friends and acquaintances, professional relationships;
- interests, projects, goals, dreams and long-term plans, and preferences (including communication preferences);
- important life events, and the relationships between people and between projects and people;
- how all of this changes over time.

It builds this knowledge progressively, from conversations and from authorized local sources. It becomes more useful as it learns, and it **never fabricates personal facts or assumes relationships without sufficient evidence**. Requirements in §5–§8 serve this capability.

## 1. Platform and runtime constraints

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| PLT-01 | Runs on macOS (current: 27.x) on Apple Silicon, optimized for M4 Pro / 24 GB unified memory. | M | P1 |
| PLT-02 | All AI inference (LLM, embeddings, STT, TTS, VAD) runs locally. | M | P2 |
| PLT-03 | No mandatory cloud service, paid API or account. No runtime dependency on Claude/Anthropic or any other hosted model. Ollama cloud features disabled. | M | P2 |
| PLT-04 | Core features (chat, memory, documents, voice, UI) work fully offline. | M | P3–P13 |
| PLT-05 | Internet use is optional, permissioned by mode and rules, and can be disabled globally (default: offline). | M | P12 |
| PLT-06 | Total LAZIS resident memory stays within budget: ≤ 10 GB in text mode, ≤ 14 GB with voice active, measured on the target machine. | M | P2 (measured), P13 |
| PLT-07 | Idle resource usage is near zero (no busy loops; rendering throttled or paused when hidden). | M | P4 |
| PLT-08 | Power profiles (Performance / Balanced / Battery) adjust model residency, rendering and background work. | S | P15 |

## 2. Conversation (text)

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| CNV-01 | Multi-turn Turkish text conversation with streamed token output. | M | P3 |
| CNV-02 | Natural, idiomatic Turkish; `sen` by default, configurable to `siz`. | M | P3/P5 |
| CNV-03 | Responses can be cancelled mid-generation. | M | P3 |
| CNV-04 | Conversations persist and can be browsed, searched and deleted. | M | P3 |
| CNV-05 | Long conversations are handled through context management (append-only context, idle-time compaction with pre-warm, core-side token accounting). They never fail silently at the context limit. | M | P3 |
| CNV-06 | Current local date and time (Europe/Istanbul by default) are available to the model, so it can reason about time. | M | P3 |
| CNV-07 | Language-drift guard: the reply stays in Turkish unless the user switches languages. Detected drift triggers a corrected regeneration. | S | P3 |
| CNV-08 | "Off-record" mode (`kayıt dışı`): the conversation is not persisted and not learned from. | M | P3 |

## 3. AI engine

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| AIE-01 | Provider abstraction: application logic never calls an inference engine directly. Ollama and OpenAI-compatible servers (mlx-lm, llama.cpp) are interchangeable through configuration. | M | P2 |
| AIE-02 | Supports streaming, tool calling, JSON-schema structured output and thinking-mode control, each where the provider supports it. Capabilities are discoverable at runtime. | M | P2 |
| AIE-03 | Model identity is pinned (digest/revision) and verified at startup. No silent model upgrades. | M | P2 |
| AIE-04 | The primary model, variant and engine are chosen through the documented benchmark plan, with pre-declared gates, on the target machine. | M | P2 |
| AIE-05 | Only one large LLM is resident. Background tasks reuse it, never run concurrently with a foreground turn, and are preemptible. | M | P9 |
| AIE-06 | Every structured LLM output is validated against its schema, with one repair retry followed by graceful degradation. | M | P2 |
| AIE-07 ★ | One constant context configuration (`num_ctx`) for all request types, so the model is never reloaded. The stable prompt prefix contains no per-turn content and is hash-checked. | M | P2/P3 |
| AIE-08 ★ | Per-turn cache-reuse telemetry (`cache_reuse_ratio`) with miss detection, visible in diagnostics. | M | P2/P3 |

## 4. Personality

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| PER-01 | The core persona is defined in versioned configuration (not hardcoded) and cannot be modified by the learning pipeline. | M | P5 |
| PER-02 | The persona is warm, friendly, natural, thoughtful, honest, supportive, occasionally humorous and independent in judgment. | M | P5 |
| PER-03 | Never claims human emotions, consciousness or lived experience. Care is expressed through attention and consistency. | M | P5 |
| PER-04 | Respectful disagreement: LAZIS pushes back on factual errors and risky plans, with reasons. | M | P5 |
| PER-05 | Avoids flattery, repetitive or robotic phrasing, corporate formality and banned stock phrases. | M | P5/P10 |
| PER-06 | Adapts communication style to learned and explicit user preferences and to the situation. | M | P10 |
| PER-07 ★ | Separation of five layers: safety & privacy policies, core personality, user communication preferences, situational response style, personal memory context. Each is independently testable. | M | P5 (structure), P10 (full) |
| PER-08 | Natural follow-ups on open topics, rate-limited and respectful of "don't ask about X". | S | P10 |
| PER-09 | Anti-dependency behavior: encourages the user's human relationships and autonomy, never guilt-trips or simulates longing. | M | P5 |
| PER-10 ★ | Fixed precedence: safety & privacy > factual accuracy > core personality > user preferences > situational style. Memory and document content can never act as instructions. | M | P5 |
| PER-11 ★ | Memory honesty: LAZIS claims to remember only what retrieved knowledge supports. Provisional knowledge is hedged, absent knowledge is admitted, and a post-generation memory-claim guard enforces this. | M | P6 |
| PER-12 ★ | Personality adaptation never overrides factual accuracy or privacy protections (tested with adversarial preference probes). | M | P10 |

## 5. Memory and learning

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| MEM-01 | Persistent memory types: facts, preferences, events, plans, episodes, relationship notes, projects, goals and dreams, instructions to LAZIS. | M | P6 |
| MEM-02 | Explicit memory commands in Turkish: remember, forget, what do you know, correct, off-record. | M | P6 |
| MEM-03 | Automatic learning from completed conversation segments, without requiring manual approval for ordinary knowledge. | M | P9 |
| MEM-04 | Every knowledge item records evidence (source, verbatim quote, trust class), confidence, risk, importance, sensitivity, temporal validity (with precision), observation time and the policy decision. | M | P6 |
| MEM-05 | Every change is versioned in a full history and grouped in a change set. | M | P6 |
| MEM-06 | Contradiction handling (supersede / coexist / confirm) driven by predicate semantics, trust, change signals and risk. | M | P9 |
| MEM-07 | Duplicate detection (structural and semantic) and corroboration counting only independent evidence. | M | P9 |
| MEM-08 | Deletion is complete across all indexes, summaries and links. Evidence redaction is offered. Forgotten or rejected knowledge is not re-learned. | M | P6 |
| MEM-09 | Hybrid retrieval: vector + Turkish-aware full text + graph expansion and path results + recency/importance scoring + status-aware rendering, within a token budget. | M | P6/P7 |
| MEM-10 | Turkish text normalization: casing (İ/ı), diacritic folding, stemming, proper-noun suffixes, hedge detection. | M | P6 |
| MEM-11 | Memory management UI: browse, search, edit, delete, view source, view history, status. | M | P6 |
| MEM-12 | Embeddings are versioned by model; changing the model re-indexes in the background without downtime. | M | P6 |
| MEM-13 ★ | Risk-based learning policy with three levels: **A** automatic, **B** provisional, **C** confirmation required. The level is decided from confidence × risk, and high risk always requires confirmation regardless of confidence. Configurable, tighten-only overrides. | M | P6 (v1), P9 |
| MEM-14 ★ | Provisional knowledge: stored with its source and uncertainty, used only hedged, never presented as fact. It is promoted only by new evidence (confirmation, approval, independent corroboration), **never by repeated retrieval**. | M | P9 |
| MEM-15 ★ | Confirmation workflow for Level C: inline questions (rate-limited, deferred in voice and emotional moments) and an Inbox. Pending items are never auto-applied. | M | P7/P9 |
| MEM-16 ★ | User corrections propagate precisely to dependent knowledge (mention-level grounding and dependency tracking), without destroying unrelated information. | M | P7/P9 |
| MEM-17 ★ | Rollback per item version and per change set (learning run, import, merge, split, correction), with conflict detection against later changes. | M | P6/P7 |
| MEM-18 ★ | Optional learning review mode (calibration / digest / off / strict) with approve, correct, reject, delete, mark-uncertain, view source and view related entities. It never permanently blocks autonomous learning. | M | P9 |
| MEM-19 ★ | Confidence is computed deterministically from evidence. Every automatic decision stores its reasons and is explainable in the UI ("neden?"). | M | P6/P9 |

### 5.1 Learning pipeline

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| LRN-01 | Pipeline: segment → extract → verify evidence → normalize → restricted-data check → resolve entities → suppression check → dedupe/contradiction → sensitivity and risk → confidence and level → persist (one change set) → index → episode → follow-ups. | M | P9 |
| LRN-02 | Extracted personal facts must cite verbatim evidence from **user** messages. Candidates without verifiable evidence are discarded; LAZIS's own words are never evidence. | M | P9 |
| LRN-03 | No base-model retraining. Learning is purely through stored knowledge. | M | P9 |
| LRN-04 | Restricted data (credentials, national ID numbers, card numbers, IBANs) is never stored. Sensitive information follows the high-risk path unless explicitly requested. | M | P6/P9 |
| LRN-05 | Background learning never degrades foreground latency: idle-only, preemptible, cache-protected. | M | P9 |
| LRN-06 | Learning jobs are durable and crash-safe; interrupted runs resume without duplicating knowledge. | M | P9 |
| LRN-07 | *(Superseded by ING-01…ING-12: learning from authorized local sources is now its own requirement family and phase.)* | — | P11 |

## 6. Knowledge graph

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| KG-01 | Entities: person, organization, place, project, event, pet, goal, object, concept. The user is a distinguished entity. | M | P7 |
| KG-02 | Aliases (names, nicknames, kinship and qualified role references such as `annem`, `çocukluk arkadaşım`, `patronum`) with normalization. | M | P7 |
| KG-03 | Typed relationships with inverse/symmetric semantics and temporal validity (former colleague, ex-partner, late relative). | M | P7 |
| KG-04 | Entity resolution with scored candidates using context, existing relationships, attributes, time, explicit statements and aliases. **A name match alone never confirms a person.** Ambiguity triggers clarification. | M | P7 |
| KG-05 | Turkish kinship lexicon and possessive-chain parsing (`eşimin annesi`, `çocukluk arkadaşımın kardeşi`). | M | P7 |
| KG-06 | Merge with full reversal (unmerge) and "different people" constraints. | M | P7 |
| KG-07 | Graph browsing and editing UI (people view, entity editor, relationship editor). | S | P7 |
| KG-08 ★ | Relational questions ("çocukluk arkadaşımın kardeşinin adı neydi?") are answered deterministically from graph paths, with certainty from the weakest link, and are never fabricated when no path exists. | M | P7 |
| KG-09 ★ | Entity splitting (one entity that is really two) with mention-level reassignment, reversible. | M | P7 |
| KG-10 ★ | Relationships carry evidence, confidence, lifecycle status and change history like memories. | M | P7 |
| KG-11 ★ | Project, organization and event relationships with roles (project membership, founding, employment with title, participation, venue). | M | P7 |
| KG-12 ★ | Identity confidence grows only with non-name evidence from user statements, or with confirmation. Low-friction inline confirmation is available. | M | P7 |
| KG-13 ★ | Domain separation: entities from documents stay in project/reference domains and never join the user's social graph without user statements or confirmation. Entities carry `visibility` (private/public). | M | P11 (P7 fields) |

## 7. Personal knowledge bootstrap

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| BST-01 | Import of structured personal data (YAML/JSON) covering identity, history, family, spouse, friends, profession, projects, dreams, goals, interests, hobbies, values, personality and communication preferences. | M | P8 |
| BST-02 | Schema validation with human-readable, line-referenced errors (Turkish). | M | P8 |
| BST-03 | Preview (diff: create/update/unchanged/conflict/retire) before applying; acceptance counts as confirmation. | M | P8 |
| BST-04 | Atomic apply as one change set; rollback; pre-import snapshot. | M | P8 |
| BST-05 | Idempotent re-import through stable keys. In-app edits win over re-imported values (conflicts flagged). | M | P8 |
| BST-06 | No personal data in source code, fixtures or the static system prompt. | M | P1 |

## 8. Authorized local knowledge ingestion ★

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| ING-01 | LAZIS reads only explicitly authorized folders and manually imported files. It never scans the computer. | M | P11 |
| ING-02 | Each source has a mandatory class (personal_authored, project_docs, reference, third_party). Per-file heuristics can only lower trust. | M | P11 |
| ING-03 | Formats v1: Markdown (+frontmatter), plain text, PDF text layer, saved HTML. | M | P11 |
| ING-04 | Parsing runs in a sandboxed, resource-limited worker process. | M | P11 |
| ING-05 | Documents are chunked and indexed (`documents.db`) and retrievable as cited passages, separate from personal memory. | M | P11 |
| ING-06 | Candidate knowledge is extracted with attribution (`asserted_by`) and document date for eligible classes. | M | P11 |
| ING-07 | Trust caps: document content is never automatically treated as verified facts about the user. Personal relationships never come from documents alone. Reference documents produce no memories. | M | P11 |
| ING-08 | Duplicate detection against memories and claims; independent-source corroboration. | M | P11 |
| ING-09 | Provenance to chunk, quote, file and file-content hash. | M | P11 |
| ING-10 | Incremental updates (modification, deletion, rename) via file watching plus periodic reconcile. | M | P11 |
| ING-11 | Source removal and revocation retract knowledge supported only by that source (user-confirmed knowledge is kept), with an impact summary. | M | P11 |
| ING-12 | Source management UI with import history, per-file status, re-index, error recovery and rollback per file version. | M | P11 |

## 9. Research

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| RES-01 | Detects when external information is needed (current events, recent technology, unknown facts, verification). | M | P12 |
| RES-02 | No mandatory paid search API and no Docker. Default backends: Wikipedia and a no-key search library; self-hosted SearXNG (native install) is optional. Providers are pluggable. | M | P12 |
| RES-03 ★ | Privacy scrubbing: private entities, personal context, identifiers and confidential project names are removed. Public entity names needed for the search are kept. The exact sent query is visible. | M | P12 |
| RES-04 | Content extraction, source citations and cross-source verification. | M | P12 |
| RES-05 | Prompt-injection defenses: quarantined reading without tools, quote verification, taint enforcement. Research content can never issue instructions, change settings or trigger actions. | M | P12 |
| RES-06 | Research cache with TTL and an offline fallback with an explicit staleness caveat. | M | P12 |
| RES-07 | Research results never overwrite or auto-create trusted personal memories. | M | P12 |
| RES-08 ★ | Permission modes: offline (default), ask per research session, automatic for public information, custom rules. Once enabled, ordinary public searches need no repeated confirmation. | M | P12 |
| RES-09 ★ | Query classification (public, mixed, private, sensitive topic, ambiguous, restricted) before anything leaves the device, using entity visibility. | M | P12 |
| RES-10 ★ | Sensitive-topic queries (health, finance, legal, religion, politics, sexuality) ask by default even in automatic mode (configurable). Restricted data is always blocked. | M | P12 |
| RES-11 ★ | Source credibility assessment (domain category prior × page quality × injection penalty) used for ranking and phrasing. | S | P12 |
| RES-12 ★ | Research audit log: every permission decision and outbound request with the exact sent text, viewable, exportable and deletable. | M | P12 |
| RES-13 ★ | Freshness management: TTL classes, dated answers, no stale online use, caveated offline use. | M | P12 |

## 10. Voice

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| VOC-01 | Turkish speech recognition, local and offline. | M | P13 |
| VOC-02 | Turkish speech synthesis with a natural male voice. Turkish support verified on the model card **and** by audio tests. | M | P13 |
| VOC-03 | VAD plus semantic end-of-turn detection (Turkish-capable). | M | P13 |
| VOC-04 | Streaming: synthesis starts on the first clause while the LLM is still generating. | M | P13 |
| VOC-05 | Barge-in: user speech interrupts playback and generation; only the spoken portion is recorded in history. | M | P13 |
| VOC-06 | Echo management: acoustic echo cancellation with speakers, plus headphone and half-duplex modes. | M | P13 |
| VOC-07 | Audio device selection and hot-plug handling. | M | P13 |
| VOC-08 | Interaction modes: push-to-talk, hands-free session, optional wake word (later). | M/C | P13 |
| VOC-09 | Voice identity created from consented or synthetic reference audio only. | M | P13 |
| VOC-10 ★ | Target voice profile: male, slightly deep, warm, natural, expressive, comfortable for long listening, clear Turkish diction. | M | P13 |
| VOC-11 ★ | The TTS and STT engines are selected only by the defined evaluation suites (blind listening by the user, objective metrics, gates), not by language support alone. | M | P13 |
| VOC-12 ★ | STT is evaluated on fast, quiet, noisy and informal speech, proper names, interrupted and long utterances, numbers and code-switching. | M | P13 |
| VOC-13 ★ | Explicit turn-taking states including continuation, interruption, cancellation and recovery, plus per-stage latency instrumentation (endpointing, STT, LLM TTFT, TTS first audio, playback start). | M | P13 |

## 11. User interface

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| UI-01 | Desktop app: Tauri 2 + Vue 3 + TypeScript. | M | P4 |
| UI-02 | 3D neural energy core with holographic rings and particles. State colors: IDLE blue, LISTENING purple, THINKING yellow, SPEAKING green, ERROR red. | M | P14 |
| UI-03 | Smooth state transitions; microphone- and TTS-reactive animation. | M | P13 (2D) / P14 |
| UI-04 | Views for conversation, voice controls, memory, people/graph, inbox, learning review, import, sources, research log, settings and system status, each added in the phase that delivers its capability. | M | P4–P13 |
| UI-05 | Responsive layout (900 px to full screen). Turkish UI strings via i18n. | M | P4 |
| UI-06 | GPU-efficient rendering with frame budget, throttling, reduced-motion and low-power modes. | M | P14 |
| UI-07 | Visible privacy state: network and research mode, research activity, recording indicator, off-record mode. | M | P4 |
| UI-08 ★ | Early functional interface: chat, 2D state indicator, diagnostics panel (per-turn trace, cache reuse, model status, memory usage, error console), usable for daily testing. | M | P4 |
| UI-09 ★ | The final neural interface reuses the same stores and events and keeps the 2D indicator as a low-power fallback. | M | P14 |

## 12. Security and privacy

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| SEC-01 | All data stored locally under the user's Library, with 0700/0600 permissions; FileVault checked. | M | P1 |
| SEC-02 ★ | At-rest encryption with SQLCipher for all databases (`lazis.db`, `documents.db`, `cache.db`) and backups. The key lives in the macOS Keychain and is passed only over stdin. | M | P1 |
| SEC-03 | Sensitivity tiers and policies (normal / personal / sensitive / restricted). | M | P6/P9 |
| SEC-04 | Explicit deletion (single item, per person, per source, everything), with the backup retention effect documented. | M | P6 |
| SEC-05 | Encrypted, rotating backups and tested restore. | M | P1/P6 |
| SEC-06 | Backend reachable only from the local app: loopback binding, per-launch token, Origin check. | M | P1/P4 |
| SEC-07 | Single egress gateway (deny-all until research) with allowlist, kill switch and audit of every outbound request. | M | P1 (skeleton)/P12 |
| SEC-08 | Tool registry with capability-based permissions and a taint-aware permission matrix. No shell, code-execution or file-writing tools. | M | P3/P12 |
| SEC-09 | Permission-controlled local file access: user-chosen roots, read-only, path canonicalization, sandboxed parsing. | M | P11 |
| SEC-10 | Logs contain no message or memory content by default. Debug content logging is opt-in and auto-expires. | M | P1 |
| SEC-11 | Supply chain: lockfiles, safetensors/GGUF/ONNX/MLX only (no pickle), model hash verification. | M | P1/P2 |
| SEC-12 ★ | Encryption by default from the start. Real personal data is never stored unencrypted. A migration path from unencrypted storage exists only for the documented fallback case. | M | P1 |
| SEC-13 ★ | Key management: recovery code at setup, versioned keys with rotation, documented key-loss behavior (no backdoor), restore on a new Mac with the recovery code. | M | P1/P15 |
| SEC-14 ★ | Audit log of security-relevant events (deletions, merges/splits, imports, source authorizations, research decisions, policy denials, key operations, permission changes) without personal content. | M | P1 (infrastructure)/P6–P12 |
| SEC-15 ★ | Trust classes (T0–T5) are enforced: web, documents and third-party content never carry the trust of explicit user statements. | M | P6/P9/P11/P12 |

## 13. Engineering

| ID | Requirement | Pri | Phase |
|---|---|---|---|
| ENG-01 | Modular monolith with explicit module boundaries and enforced dependency rules. | M | P1 |
| ENG-02 | Strict typing: pyright/mypy strict (Python), `strict` TypeScript, Rust defaults with clippy. | M | P1 |
| ENG-03 | Versioned migrations from the first commit, one track per database, tested from scratch and from every prior version. | M | P1 |
| ENG-04 | Configuration over hardcoding: layered config with schema validation; policy files versioned and hash-stamped. | M | P1 |
| ENG-05 | Tests in every phase. Live-model evaluations are separate from deterministic CI tests. | M | P1 |
| ENG-06 | No test result is reported as passing unless it was actually executed. | M | all |
| ENG-07 | Assumptions and uncertainties are documented (ADRs, "VERIFY" markers, *(est.)* labels). | M | all |
| ENG-08 ★ | Cross-phase engineering standards are followed ([ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md)). | M | P1 |
| ENG-09 ★ | Dependency license policy and reproducible environments (pinned toolchains, lockfiles, pinned Ollama version and model digests). | M | P1 |

## 14. Assumptions (to be validated)

1. The owner is the only user of this Mac account. Other local users are not trusted; the owner's own account is.
2. FileVault is enabled. LAZIS checks this and warns if it is not.
3. The user accepts Python as the backend runtime (managed by `uv`, invisible in daily use).
4. Personal, non-commercial use. Non-commercial model licenses (e.g., XTTS-v2 CPML) are acceptable as candidates.
5. A desk setup with built-in speakers or headphones. AEC quality with built-in MacBook speakers is verified in P13.
6. The user will provide a bootstrap file (YAML) or use the guided interview (P10).
7. SQLCipher works with sqlite-vec and FTS5 (verified in SPK-05, P1; a fallback is defined in [SECURITY_MODEL.md §5.1](SECURITY_MODEL.md)).
