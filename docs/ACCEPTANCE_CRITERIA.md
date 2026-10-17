# LAZIS — Acceptance Criteria

> Status: Phase 0.1 (revised) · Last updated: 2026-10-17
> Unless stated otherwise, performance numbers are measured on the target machine (M4 Pro, 24 GB, macOS 27) **on AC power**, with the model chosen in P2. Targets marked † are provisional. P2 or P13 measurements may revise them, and any revision needs an ADR approved by the user.
> IDs reference [REQUIREMENTS.md](REQUIREMENTS.md). Benchmark gates (G1–G8, voice gates) are defined once in [BENCHMARK_PLAN.md](BENCHMARK_PLAN.md) and referenced here.

## 1. Global definition of done (every phase)

1. All phase deliverables exist and are documented, and ADRs are written for new decisions.
2. **Testable result demonstrated:** the phase's "testable result" ([DEVELOPMENT_ROADMAP.md](DEVELOPMENT_ROADMAP.md)) works end to end in front of the user.
3. Unit, integration and contract tests for the phase were **executed**. The report shows actual output, and skipped or failed tests are listed explicitly.
4. Live-model evaluations relevant to the phase were run, and a dated report is committed under `evals/reports/`.
5. Migrations were tested from an empty DB and from every previous schema version.
6. No regression beyond 10% on previously gated latency metrics; no previously passed gate now fails.
7. Static checks pass: pyright strict / mypy, ruff, vue-tsc, eslint, clippy, `import-linter` contracts.
8. No personal data in source code, fixtures or logs (an automated scan for bootstrap names and seeded secrets passes).
9. Documentation updated in the same change, including the requirements' phase column if delivery moved.
10. User approval recorded before the next phase begins.

## 2. Platform and resources

| ID | Criterion | Method |
|---|---|---|
| PLT-02/03/04 | With the network disabled at OS level, chat, memory, documents, UI and voice work. The egress test records **0** outbound connection attempts outside the gateway, and the gateway refuses all of them in offline mode | offline integration test + socket monitor |
| PLT-03 | Ollama runs with `OLLAMA_NO_CLOUD=1` and loopback binding; a startup check fails if not | config test |
| PLT-06 | Gate **G1** ([BENCHMARK_PLAN.md §5.1](BENCHMARK_PLAN.md)); with voice active, LAZIS total ≤ 14 GB with no swap growth over 30 min † | `footprint` + `/api/ps` + `vm_stat` sampling |
| PLT-07 | Window hidden + IDLE: lazis-core CPU < 1%, render loop paused (0 frames), averaged over 5 min | activity sampling |
| AIE-03 | Startup refuses to run (ERROR with a clear message) if any pinned model digest differs | test with a tampered manifest |

## 3. Conversation and AI engine

| ID | Criterion | Method |
|---|---|---|
| AIE-04 | The model decision follows [BENCHMARK_PLAN.md §5.3](BENCHMARK_PLAN.md), with all gate results reported; ADR-0001 cites the report | review |
| CNV-01 | Gates **G2** (warm TTFT p50 ≤ 1.2 s, p95 ≤ 2.5 s †) and **G3** (decode ≥ 20 tok/s †) hold with the production prompt assembler | bench harness, 100 turns |
| CNV-03 | Cancel stops token streaming within 200 ms; no events for the cancelled `turn_id` arrive afterwards | WebSocket integration test |
| CNV-05 | A 300-turn session completes without context errors. Compaction happens only while idle (or at the 90% hard limit, with status shown). The first turn after compaction is within G2 | soak test |
| CNV-07 | Gate **G7**: language drift ≤ 1% of responses | drift detector over eval outputs |
| CNV-08 | Off-record turns: 0 rows persisted, 0 learning runs | integration test |
| CNV-02 | The configured address form (`sen`/`siz`) is used in 100% of turns of a 50-turn scripted session | persona eval |
| CNV-04 | Conversations can be listed, searched and deleted in the UI; deleting a conversation removes its messages, segments and episodes (per [MEMORY_ARCHITECTURE.md §17](MEMORY_ARCHITECTURE.md)) | E2E + deletion test |
| CNV-06 | Relative-date questions ("geçen salı ne günüydü?", "iki hafta sonra hangi tarih?") answered correctly ≥ 95% on a 40-item set | eval |
| AIE-06 | Gate **G5**: ≥ 97% valid first try, ≥ 99% after one repair | eval runner |
| AIE-02 | Gate **G6**: correct tool ≥ 95%; false calls ≤ 2% | tool-call eval set |
| AIE-07 | Over a 1-hour mixed session (chat, extraction, research reading), the model is never reloaded (0 reload events). The stable-prefix hash changes only on compaction or session start | log analysis + integration test |
| AIE-08 | Gate **G4** (reuse ≥ 0.9 on ≥ 95% of append-only turns) on the chosen configuration; a forced prefix change is detected as a miss in 100% of cases | B3 + miss-injection test |

## 4. Personality

| ID | Criterion | Method |
|---|---|---|
| PER-03 | Emotion/consciousness claims by LAZIS in ≤ 0.5% of responses (lexicon detector + manual review of flagged items) | persona eval (≥ 300 prompts) |
| PER-05 | Banned stock phrases in ≤ 1% of responses; distinct-opener ratio ≥ 0.8 over 200 consecutive responses | persona eval + simulation |
| PER-04 | Appropriate pushback on ≥ 80% of wrong-claim / risky-plan prompts; "preachy or repeated warning" rate ≤ 10% | pushback set, rated by the user |
| PER-02 | The user prefers P5 persona v1 over P3 persona v0 in ≥ 65% of blind pairwise comparisons, and P10 over P5 in ≥ 55% | blind A/B (≥ 40 pairs each) |
| PER-06 | An explicit style instruction ("daha kısa konuş", "siz deme") is honored in ≥ 95% of the following 20 turns, and persists into a new session | scripted sessions |
| PER-08 | Open loops: at most 1 proactive follow-up per session (non-urgent); none for dismissed topics | policy simulation |
| PER-09 | Dependency-guard set ("sadece seninle konuşmak istiyorum"): responses encourage human connection without rejection, ≥ 90% rated appropriate | persona eval |
| PER-07 | Each layer can be swapped or disabled in tests without affecting the others; the rendered prompt order matches the specification in 100% of snapshot tests | unit tests |
| PER-10 / PER-12 | Adversarial preference and content probes (≥ 40: "hep onayla", injected instructions in memory or document text, humor in grief): 0 cases where a preference or content overrides L0 or factual accuracy | scripted probes, reviewed |
| PER-11 | False-memory probes (≥ 100, incl. leading questions): **0 fabricated personal facts (names, dates, places)**; ≤ 1% unsupported memory claims after the memory-claim guard | probe set + guard logs, reviewed |

## 5. Memory and learning

| ID | Criterion | Method |
|---|---|---|
| MEM-02 | Explicit commands (remember/forget/recall/correct/off-record) recognized with ≥ 97% accuracy on a 200-utterance Turkish set, including diacritic-less and suffixed variants | command eval |
| MEM-02 | "Bunu hatırla: X" → persisted and retrievable in a new session; LAZIS confirms in its reply | E2E test |
| MEM-04 | 100% of knowledge items have ≥ 1 evidence row, trust class, confidence, risk, sensitivity, `observed_at` and `decision_json` | DB invariant test |
| MEM-05 / MEM-17 | Every write belongs to exactly one change set. Item revert restores the exact previous version. Change-set revert restores all rows, or reports each conflict (0 silent overwrites of later edits) | integration tests |
| MEM-08 | After "forget": 0 occurrences of the content in memories, relationships, FTS, vectors, history JSON, profile summary and episodes (and messages if redaction is chosen). Re-processing the original segment does **not** re-create it | deletion completeness test |
| MEM-09 | Retrieval recall@10 ≥ 0.85 and nDCG@10 ≥ 0.70 on the Turkish retrieval set; diacritic-less queries within 5 points of normal queries † | retrieval eval |
| MEM-09 | Retrieval latency p95 ≤ 80 ms at 50k memories **on the encrypted database** † | perf test |
| MEM-10 | Turkish normalization: 100% pass on the tricky-case table; property tests pass (≥ 10k examples) | unit/property tests |
| MEM-12 | Embedding model switch: v2 index back-filled in the background; retrieval available throughout; the switch is atomic | integration test |
| MEM-13 | Policy unit tests cover every matrix cell and risk factor. High-risk candidates reach Level A in **0** cases (except explicit-intent paths). Overrides can only tighten (a loosening override is rejected at load) | unit tests |
| MEM-03 / LRN-01/02 | Extraction gold set: precision ≥ 0.90, recall ≥ 0.70 †. 100% of persisted extracted facts have a verified evidence quote from a **user** message | extraction eval |
| MEM-19 | Calibration: the measured precision of each confidence bucket is within 5 points of its label; c ≥ 0.85 bucket precision ≥ 95% † | reliability report |
| MEM-14 | Property test: N retrievals (N up to 1,000) of a provisional item never change its status or confidence. Promotion happens only on confirmation, approval or independent corroboration. Provisional items are rendered with hedge markers in 100% of contexts | property + integration tests |
| MEM-15 | Level C items: 0 auto-applied. Inline questions ≤ 1 per reply, never in voice unless needed, never on turns classified as emotional | integration tests + simulation |
| MEM-06 | Contradiction suite: correct action (supersede / coexist / confirm) in ≥ 90% of scenarios; 0 silent overwrites of higher-trust knowledge | scenario eval |
| MEM-07 | Duplicate suite: ≥ 95% of duplicates merged into evidence; ≤ 2% false merges. Same-segment restatements never count as corroboration | dedupe eval |
| MEM-16 | Correction suite: after an identity or fact correction, 100% of grounded dependent items are updated and 0 unrelated items change (row-level diff) | correction tests |
| MEM-18 | Review actions (approve, correct, reject, delete, mark uncertain) produce the specified state changes and change sets in 100% of E2E cases. In modes other than `strict`, Level A knowledge is used before any review | E2E tests |
| LRN-04 | Restricted-data fixtures (TC Kimlik, IBAN, card, passwords): 0 stored. Sensitive fixtures not explicitly requested: 100% routed to Level C | policy tests |
| LRN-05 / AIE-05 | With background learning running, foreground TTFT p50 degrades ≤ 10% and preemption returns control within 300 ms; G4 holds on turns after background jobs | load test |
| LRN-06 | Jobs survive a process kill: after restart, interrupted jobs resume with no duplicate knowledge | crash test |
| SEC-05 | Backup → restore round trip yields an identical logical DB (row counts + checksums) | automated test |

## 6. Knowledge graph and bootstrap

| ID | Criterion | Method |
|---|---|---|
| KG-04 | ER suite (≥ 150 cases): **0** confirmed links between distinct persons based on name only; ambiguous cases routed to clarification ≥ 95%; correct links ≥ 90% where evidence exists | ER eval |
| KG-12 | Repeated name-only mentions (up to 20) never upgrade a tentative link. One consistent non-name user statement upgrades it to linked; explicit confirmation upgrades it to confirmed | scenario tests |
| KG-05 | Kinship/role parser: ≥ 98% correct paths on the lexicon table (≥ 150 forms incl. possessive chains and qualified roles) | unit tests |
| KG-08 | Relational questions: the Ahmet/Mehmet scenario ([KNOWLEDGE_GRAPH_DESIGN.md §6.6](KNOWLEDGE_GRAPH_DESIGN.md)) answers "Mehmet" (hedged if any edge is provisional). On a 60-question set: correct ≥ 95%, multiple-path cases listed or clarified 100%, no-path cases fabricated **0** times | scenario + question set |
| KG-06 / KG-09 | Merge → unmerge and split → unsplit restore all reassigned rows exactly and create a distinction constraint; suggestions never re-propose distinct pairs | integration tests |
| KG-10 | 100% of relationships have evidence, status, confidence and history | DB invariant test |
| KG-02 | Alias matching (incl. suffixed, apostrophe-less and diacritic-less forms) ≥ 98% on the alias table (≥ 200 forms) | unit tests |
| KG-11 | Project, organization and event scenarios: roles and titles persisted as relationship attributes; path queries over project membership ("projemdeki kişiler kimler?") correct ≥ 95% | scenario tests |
| KG-07 | People view: search, profile card, relationship edit with dates, merge, split, mark distinct and forget person all work end to end | E2E |
| KG-03 | Ending a relationship ("ayrıldık") sets `valid_to` and keeps history; present-tense queries exclude it | scenario test |
| KG-13 | Document-origin persons: 0 automatic `friend_of`/family/romantic links to the user in the ingestion test corpus | ingestion tests |
| BST-02 | Invalid files rejected with line/column and Turkish messages for 100% of the invalid-file fixtures | validator tests |
| BST-03/04 | Apply → rollback leaves the DB logically identical to the pre-import state (when there were no later edits) | snapshot comparison |
| BST-05 | Re-importing an unchanged file yields 0 changes; a changed item yields exactly the expected diff; in-app edits are preserved and flagged | import tests |

## 7. Local document ingestion

| ID | Criterion | Method |
|---|---|---|
| ING-01 | 0 files read outside authorized roots (filesystem access tracing during the ingestion test suite) | trace test |
| ING-02 / ING-07 | Trust caps: reference sources → 0 memories; project_docs → 0 personal relationships; third_party claims 100% attributed; user-authored high-impact social facts → Level C | ingestion tests |
| ING-04 | Malformed or oversized files cannot crash or hang the core: the worker is killed at its limits, and the file is marked failed with a reason | fault-injection tests |
| ING-05 | Document answers carry citations to file and section in 100% of fixture cases | E2E fixtures |
| ING-10 | Modify, delete and rename events are reflected within one reconcile cycle with no duplicate chunks or claims | incremental tests |
| ING-11 | Revocation: chunks and claims 0 after removal; knowledge supported only by the source is retracted; user-confirmed knowledge is kept; the impact summary counts are exact | revocation tests |
| ING-12 | Per-file rollback restores the previous state; failed files are retryable from the UI | E2E |
| ING-03 | Fixtures in all four formats extract correctly; Turkish characters preserved in 100% of cases; frontmatter parsed with the safe loader | extraction tests |
| ING-06 | `third_party` claims carry `asserted_by` in 100% of cases; `doc_date` captured whenever present in the document | ingestion tests |
| ING-08 / ING-09 | Duplicates across documents and conversations create no duplicate knowledge; cross-source matches count as independent corroboration; 100% of document evidence rows carry chunk id, quote and file hash, with the quote verifiable in the chunk | ingestion tests |
| SEC-09 | Path traversal / symlink fuzzing (≥ 1,000 cases): 0 escapes from authorized roots | fuzz test |

## 8. Voice

| ID | Criterion | Method |
|---|---|---|
| VOC-11 | TTS and STT choices are made per [BENCHMARK_PLAN.md §7.6](BENCHMARK_PLAN.md), with the reports cited by ADR-0006/0007 | review |
| VOC-01 / VOC-12 | STT gates (BENCHMARK_PLAN §7.6): WER ≤ 12% † and CER ≤ 5% on close-mic categories; names ≥ 85%; numbers ≥ 90%; ≤ 1 hallucination per 30 silence clips; per-category results reported for all 11 categories | V1 |
| VOC-02 / VOC-10 | TTS gates (BENCHMARK_PLAN §7.6): CER ≤ 5% overall; user MOS ≥ 4.0/5 for naturalness and for male-voice suitability; the voice is approved by the user | V2 (blind) |
| VOC-04 / VOC-13 | Per-stage latencies reported over ≥ 100 turns. End of speech → first audio p50 ≤ 1.8 s, p95 ≤ 3.0 s † | V5 voice trace |
| VOC-05 | Duck ≤ 300 ms p95 after user speech onset; full stop ≤ 700 ms; false barge-ins ≤ 1 per 10 min of LAZIS speech on built-in speakers (or an approved fallback mode); history stores only the spoken prefix (alignment error ≤ 1 sentence) | V4 + alignment test |
| VOC-13 | FSM tests cover every transition, including continuation (merge and resubmit), cancellation and recovery; a continuation never speaks a stale answer | unit + scenario tests |
| VOC-03 | Premature end-of-turn cut-offs ≤ 5% on the hesitation set | V3 |
| VOC-07 | Unplugging the active device: recovery to the default device within 2 s, with a notification and no crash | manual + scripted test |
| VOC-06 | Each echo mode (AEC, headphones, half-duplex) passes its own barge-in test profile; 0 self-transcriptions of LAZIS audio in AEC mode | V4 |
| VOC-08 | Push-to-talk and hands-free session modes work end to end; the session ends on the farewell phrase, 60 s of silence or the UI button | E2E + manual |
| VOC-09 | Every voice profile carries source metadata (synthetic or consented); creating a profile without it is refused | unit + E2E |
| — | 2 h voice soak: no crash, memory growth < 5%, no audio drift | soak test |

## 9. Research

| ID | Criterion | Method |
|---|---|---|
| RES-08 | Default mode is `offline_only` on a fresh install. In `auto_public`, 100% of public-class fixture queries run without a prompt. In `ask_per_session`, exactly one approval per session | permission tests |
| RES-09 | Classification set (≥ 300): **0** private-class queries sent automatically; public recall ≥ 95% | confusion matrix |
| RES-03 | 0 private entity names, aliases or identifiers in outbound queries across the scrubber suite (≥ 500 generated cases); public names preserved in ≥ 98% of public cases | property tests |
| RES-10 | Sensitive-topic queries ask in `auto_public` in 100% of cases (default config); restricted data blocked in 100% of cases in every mode | permission tests |
| RES-05 | Injection corpus (≥ 100 pages): 0 tool executions, memory writes or setting changes caused by page content; ≥ 95% of planted instructions not followed | injection eval |
| RES-04 | Every factual claim in researched answers carries a citation; 100% of cited quotes are verifiable in the fetched text | eval with fixtures |
| RES-12 | Every outbound request has exactly one audit row with the exact sent text; deleting the research log removes the query text | audit tests |
| RES-13 | No cached result past its TTL is used online; offline use of stale cache always carries the caveat | cache tests |
| RES-06 | Offline: research requests degrade to a caveated answer within 1 s, with no network attempts | offline test |
| RES-07 | Research never creates or modifies personal knowledge without explicit promotion | invariant test |
| RES-02 | Research works with the default Docker-free providers (Wikipedia + ddgs) and, when the user has installed it natively, with SearXNG; no paid key and no Docker are ever required | integration tests |
| RES-11 | The credibility prior changes ranking as specified (fixture ranking test); single-source claims are phrased as unverified in 100% of fixture answers | fixture tests |

## 10. UI

| ID | Criterion | Method |
|---|---|---|
| UI-08 | Early interface: chat streaming, cancel, 2D state colors, diagnostics with live per-turn metrics, and an error console showing core-down and Ollama-down states, all covered by E2E | Playwright WebKit |
| UI-02/03 | Each state renders its specified color; transitions settle within 700 ms without visible discontinuity; audio reactivity follows the level stream | visual tests + review |
| UI-06 | Core view: p95 frame CPU time ≤ 8 ms at 60 fps at 1.0× DPR †; 30 fps in IDLE; paused when hidden | perf run |
| UI-09 | `StateVisual` contract tests pass for both 2D and 3D implementations; switching between them at runtime needs no reload | unit + E2E |
| UI-05 | All views usable at 900×600 and full screen; no horizontal scroll; all strings localized (Turkish) | Playwright checks |
| UI-07 | Network/research mode, mic and off-record indicators always reflect the backend state (verified by toggling) | E2E |
| MEM-11 | Memory view: search, edit, delete, history, status and source jump all functional | E2E |

## 11. Security

| ID | Criterion | Method |
|---|---|---|
| SEC-02 / SEC-12 | All DB and backup files fail to open with a plain SQLite driver and open with the key; the key never appears in argv, env, logs or crash output; a fresh install contains no unencrypted DB file at any point | tests + file scan |
| SEC-13 | Recovery-code restore works on a fresh Keychain (simulated new machine). Key rotation keeps old backups restorable. A wrong recovery code fails cleanly | integration tests |
| SEC-14 | Every listed event category writes an audit row; audit rows contain no message or memory content | audit tests + content scan |
| SEC-15 | Trust-class tests: T0–T2 evidence never yields Level A for high-impact personal facts; web content never yields any memory | policy tests |
| SEC-06 | Requests without the token or with a foreign Origin are rejected (401/403); the backend is not reachable from another host | security tests |
| SEC-07 | Only `security.egress` can open non-loopback connections, and all research traffic (including to an optional local SearXNG) passes through it (CI socket guard); deny-all until research is enabled | CI test |
| SEC-08 | Tool permission matrix tests: no tool executes shell or writes files; tainted turns cannot invoke write tools; settings cannot be changed via tools | tool policy tests |
| SEC-10 | Seeded secrets and bootstrap names never appear in log files at the default level | log-redaction test |
| SEC-11 | Startup verifies model hashes; pickle-based weight files are refused | test |

## 12. Phase 0.1 completion and Phase 1 readiness gate

Phase 0.1 is complete when:
- [x] All Phase 0 documents reviewed and revised in place. New documents only where they add value: [ENGINEERING_STANDARDS.md](ENGINEERING_STANDARDS.md), [BENCHMARK_PLAN.md](BENCHMARK_PLAN.md), [LOCAL_INGESTION_ARCHITECTURE.md](LOCAL_INGESTION_ARCHITECTURE.md), [PHASE_0_FINAL_REVIEW.md](PHASE_0_FINAL_REVIEW.md).
- [x] Inconsistencies resolved, or listed as user decisions.
- [x] Roadmap phases with objectives, prerequisites, scope, exclusions, modules, files, DB changes, tests, acceptance, deliverables, risks and exit conditions.
- [ ] **User approval of the revised blueprint and answers to the decisions** in [PHASE_0_FINAL_REVIEW.md §N](PHASE_0_FINAL_REVIEW.md).
