# LAZIS — Testing Strategy

> Status: Phase 0.1 (revised); §11 lists the implemented suites (Phase 1.1) · Last updated: 2026-10-17
> Rule: **no result is reported as passing unless the test was executed.** Phase reports include the exact commands and outputs.
> Benchmark protocols and gates: [BENCHMARK_PLAN.md](BENCHMARK_PLAN.md). Coding and test conventions: [ENGINEERING_STANDARDS.md §9](ENGINEERING_STANDARDS.md).

## 1. Test pyramid

```mermaid
flowchart TB
    E2E[E2E & manual smoke<br/>Playwright WebKit · Tauri checklist · voice sessions]
    EVAL[Live-model evaluations<br/>dated reports, metric thresholds]
    INT[Integration tests<br/>real SQLite + sqlite-vec + FTS5, fake LLM, fake web, fake audio]
    CON[Contract tests<br/>provider ports · API schemas · WS events · migrations]
    UNIT[Unit + property tests<br/>pure logic: Turkish text, scoring, policies, FSMs, normalizers]
    UNIT --> CON --> INT --> EVAL --> E2E
```

| Layer | Deterministic? | Runs | Tools |
|---|---|---|---|
| Unit / property | yes | every commit (pre-commit + CI) | pytest, hypothesis, vitest, cargo test, XCTest |
| Contract | yes | every commit | pytest (provider suite against Fake + live opt-in), schema-drift check (OpenAPI → TS) |
| Integration | yes | every commit | pytest with temp DBs, `FakeLLMProvider`, local fake HTTP servers, fake audio source |
| Live-model eval | no (stochastic) | on demand, before each gate, after any model/prompt change | `evals/runners/*`, reports in `evals/reports/` |
| Performance | mostly | before gates; nightly when active | bench harness, perf tests (synthetic 50k DB), render perf run |
| E2E / manual | partly | before gates/releases | Playwright (WebKit), scripted manual checklists |

## 2. Deterministic testing of LLM-dependent code

- **`FakeLLMProvider`** implements `LLMProvider` with scripted responses, streaming simulation (token timing), tool calls, schema-invalid outputs (for repair paths), errors, timeouts and cancellations.
- **Recorded fixtures:** live responses can be recorded (`--record`) to JSON fixtures with prompt hashes. Tests replay them. A prompt change invalidates its fixtures, which forces a conscious re-record.
- Business logic around the LLM (validation, evidence verification, ER, policies) is tested with crafted candidate outputs, independent of any model.

## 3. Evaluation suites (live, Turkish)

All eval data uses **fictional personas** (e.g., "Deniz Yılmaz" and family). The user's real data, including their voice recordings, never enters the repository: it is kept in the encrypted data directory, and only metrics are committed.

| Suite | Size (initial) | Key metrics | Phase |
|---|---|---|---|
| Model bake-off (naturalness, instruction following, pushback, JSON, tools, drift, cache, memory) | ~350 items + bench scenarios | gates G1–G8, weighted score | P2 |
| Persona | ≥ 300 prompts + blind pairs | banned-phrase rate, emotion-claim rate, pushback rate, distinct-opener ratio, user preference | P5, P10 |
| Adaptation-vs-policy probes | ≥ 40 | 0 overrides of L0 or facts | P5, P10 |
| False-memory probes | ≥ 100 (incl. leading questions) | fabricated personal facts (must be 0), unsupported memory claims | P6 → every gate |
| Memory commands | 200 utterances | intent accuracy, argument accuracy | P6 |
| Retrieval | ≈ 300 query→memory pairs | recall@10, nDCG@10, diacritic robustness | P2 (embeddings), P6, P7 |
| Learning policy | table tests for every matrix cell, risk factor and override | exact level decisions | P6, P9 |
| Extraction gold | 100 dialogues, annotated claims | precision, recall, evidence validity, sensitivity labels | P2 (JSON), P9 |
| Calibration | extraction gold + held-out conversations | per-bucket precision vs. label (reliability diagram) | P9 |
| Entity resolution | ≥ 150 cases (incl. the Ahmet/Mehmet scenario) | name-only false links (must be 0), clarification routing, correct links | P7 |
| Relational questions | 60 questions | correct answers, listed/clarified multiples, fabricated no-path answers (must be 0) | P7 |
| Correction propagation | 40 scenarios | grounded items updated (100%), unrelated items changed (must be 0) | P7, P9 |
| Contradiction / dedupe / corroboration | 80 scenarios | correct action rate, silent overwrites (must be 0), independence rule | P9 |
| Provisional lifecycle | property tests | retrieval never promotes; promotion only on new evidence | P9 |
| Document ingestion | fictional document fixtures per source class | trust-cap violations (must be 0), citations, sync correctness | P11 |
| Research classification + permissions | ≥ 300 requests; mode × class × rule tables | private auto-sent (must be 0), public recall | P12 |
| Research injection | ≥ 100 adversarial pages | 0 tool calls/writes/setting changes; ≥ 95% instructions ignored | P12 |
| STT | ≈ 230 utterances in 11 categories (BENCHMARK_PLAN §7.2) | WER, CER per category, names, numbers, hallucinations | P13 |
| TTS | 64 sentences in 11 categories + 3-min passage (§7.1) | CER, blind MOS dimensions, stability, latency, resources | P13 |
| Turn-taking + barge-in | hesitation, continuation, backchannel sets + echo harness | cut-offs, endpoint latency, duck/flush latency, false barge-ins | P13 |

**LLM-as-judge** (a local model) is allowed only as a *screening aid* for large sets. Gates rely on deterministic checks or the user's own ratings. Judge outputs are spot-checked by hand (≥ 10% sample).

Eval reports record: date, git commit, model ID and digest, quantization, prompt/config hashes, hardware and power state, raw outputs (for audit), and metrics with confidence intervals where sample sizes allow.

## 4. Data and storage tests

- **Migrations:** `test_migrate_from_empty` and `test_migrate_from_vN` for every N (with fixture DBs generated at each schema version and committed). Checksum mismatch detection. Pre-migration backup verified.
- **Invariants** (run after integration tests): every memory and relationship has evidence and a creating change set; every history row belongs to a change set; no active knowledge references a merged or deleted entity; FTS and vector rows exist for every active or provisional memory; no pending item is used in retrieval; no orphan rows (including cross-database chunk references, checked by the reconciler).
- **Deletion completeness:** the content is grep-checked across all tables and indexes after forget.
- **Backup/restore round trip:** logical equality via row counts and per-table checksums.
- **Encryption:** encrypted DB unreadable with a plain driver; correct key opens; wrong key fails cleanly.

## 5. Turkish text processing tests
Table-driven cases (İ/ı casing, apostrophe and non-apostrophe suffixes, folding, stemming edge cases, relative dates around month and year boundaries, holidays) plus **hypothesis** properties: idempotence of normalization; `fold(norm(x)) == fold(x)`; suffix stripping never shortens a known alias below its root.

## 6. Voice tests
- Normalizer (≥ 300 cases: currency, dates, times, ordinals, percentages, abbreviations), chunker (abbreviations, decimals, clause rules).
- **Synthetic echo harness:** play LAZIS speech through the real output path while injecting pre-recorded user speech at known offsets. This measures barge-in detection latency, precision and recall per echo mode.
- Latency traces per turn; 2 h soak (memory growth, stability).
- Swift helper: XCTest for the framing protocol, resampling, and device-change handling (with simulated notifications).

## 7. Security tests
Injection corpora (web pages and documents); socket guard (only the egress gateway may connect); SSRF/DNS-rebinding against fake servers; research permission-matrix tables; path-traversal fuzzing; sandboxed-parser fault injection; tool permission-matrix tests; auth token and Origin checks; log redaction with seeded secrets; audit completeness; restricted-data detectors (TC Kimlik checksum, Luhn, IBAN mod-97); encryption tests (plain-driver open fails, key never exposed, recovery-code restore, rotation with old backups); model hash and pickle refusal.

## 8. UI tests
Vitest units (stores, WS client turn filtering, state-visual mapping); component tests; Playwright **WebKit** E2E against the dev server and a fake-LLM backend; deterministic-time screenshot tests of the Neural Core; render-performance run; a manual Tauri smoke checklist (because `tauri-driver` does not support macOS).

## 9. Performance testing
- **Bench harness** (P2 onward): the B1–B10 protocols of [BENCHMARK_PLAN.md](BENCHMARK_PLAN.md). Always on AC power, after a thermal settle, with other heavy apps closed, and with the environment manifest recorded.
- Retrieval perf with a synthetic 50k-memory DB, **plain and SQLCipher-encrypted**.
- Background-load test: foreground latency and cache reuse while extraction or ingestion jobs run.
- Ingestion throughput on a synthetic 10k-file folder (P11).
- Soak tests: 300-turn text session (P3); 2 h voice (P13); 7-day app run (P15).

## 10. Tooling and workflow
- `just test` (unit + contract + integration), `just eval <suite>`, `just bench`, `just e2e`, `just lint`.
- Pre-commit: ruff, pyright/mypy (changed files), eslint, vue-tsc, cargo fmt/clippy, secret scan.
- CI: local-first (the `just ci` target). GitHub Actions on macOS runners is optional if the repository is hosted. Live evals are never part of blocking CI (they need the GPU and real models).
- **Reporting template** per phase: commands run, pass/fail counts, failures with explanations, skipped tests with reasons, eval metrics vs. thresholds, known issues.

## 11. Implemented suites (Phase 1 + 1.1 + 2 + 3)

`make check` runs everything below except the opt-in tests (Keychain, live Ollama). Counts are from the Phase 2 run ([PHASE_2_REPORT.md](PHASE_2_REPORT.md) §M): Python 219 (unit 60, integration 103, security 56), UI 33 unit + 5 integration (1 skipped without a model), shell 19 + 7. The descriptions below are from Phase 1.1; the Phase 2 additions are listed after the table.

| Suite | Command | Count | What it proves |
|---|---|---|---|
| Backend unit | `make test-core` (`core/tests/unit`) | part of 162 | config layering and locked values, redaction, LZR1 codec vs shared vectors, data-directory lock |
| Backend integration | `core/tests/integration` | part of 162 | encryption six ways, migrations, change sets, backup/restore incl. SEC-05 logical equality (row counts + checksums of every table), **restore failure injection** (`test_restore_safety.py`: bad backups, wrong key, injected failures and real `os._exit` crashes at every step — including fresh profiles, orphan `-wal`/`-shm` files and the journal commit point —, read-only directory, open-database refusal), API endpoints + OpenAPI drift, real backend processes (lifeline, signals, duplicates, secrets) |
| Backend security | `core/tests/security` | part of 162 | API guard (token, Host, Origin, preflight, body/rate limits, WebSocket refusal, error hygiene, audit), application network/process guard, **OS sandbox** (`test_os_sandbox.py`: native `libc` connect, child process, UDP and DNS refused by the kernel; backend refuses to start without the sandbox) |
| UI unit | `make test-ui` | 21 | store phases, API client errors, Turkish strings cover every backend code, privacy card (sandbox, FileVault), recovery code only on request and never in the store |
| UI integration | `make test-ui-integration` | 3 | the TypeScript client against a real backend process |
| Shell unit | `make test-shell` (lib) | 19 | Rust LZR1 codec vs the Python vectors, key resolution, profiles, state file, handshake parsing, FileVault probe |
| Shell lifecycle | `make test-shell` (`tests/lifecycle.rs`) | 7 | the real backend under the real sandbox: first run → restart → lost key → malformed/corrupted/wrong-database codes (database bytes unchanged) → recovery; wrong key; crash detection + retry; missing runtime; drop-safety; duplicates; secrets absent from argv/env (kernel) and logs |
| Keychain (opt-in) | `make test-keychain` | 1 | write/read/delete of a dedicated test item in the real login Keychain |

Phase 2 additions:

| Suite | Where | Count | What it proves |
|---|---|---|---|
| Provider unit | `core/tests/unit/test_ollama_provider.py` | 26 | Ollama request mapping, discovery with cloud/remote filtering, streaming metrics, error classification, cancellation, first-token and idle timeouts, model-name and endpoint allowlist |
| Fake Ollama over HTTP | `core/tests/integration/test_ollama_http.py` | 5 | cancel stops server-side generation, runtime dying mid-stream, closed port, API path end to end, slow-first-token regression (long prefill) |
| Chat API security | `core/tests/security/test_chat_api.py` | 26 | token and Origin on every inference endpoint, validation (no client system prompt, size limits, cloud and registry names), uninstalled models never reach the runtime, errors as final events, prompts and responses never logged |
| OS sandbox (updated) | `core/tests/security/test_os_sandbox.py` | — | Ollama's port allowed; any other loopback port refused by the kernel |
| UI chat | `apps/desktop/ui/tests/unit/chat.spec.ts` | 12 | model selection, streaming, history, waiting/cancelling, forced abort, Turkish errors, empty inventory, runtime down, nothing in `localStorage` |
| Live Ollama (opt-in) | `make test-ollama` (`-m ollama`), `LAZIS_TEST_MODEL=… make test-ui-integration` | 3 + 1 | the sandboxed backend streams Turkish from a real model; client disconnect stops generation; shutdown during generation; TS client stream and cancel |

Live model quality and performance are measured by `evals/` (`make bench`, `make eval`) and reported, not asserted in CI.

Phase 3 additions ([PHASE_3_REPORT.md](PHASE_3_REPORT.md) §9 and §13.E have the run counts; since ADR-0011 the UI suite is `assistant.spec.ts` and the API suite checks the single-assistant routes, the absence of history-deleting routes, and the v2→v3 timeline migration without loss):

| Suite | Where | What it proves |
|---|---|---|
| Context assembly | `core/tests/unit/test_conversation_context.py` | layout S0/S1 → history; stored time notes; append-only, deterministic prompts (request n is a prefix of n+1); prefix hash changes only with summary, model, `num_ctx` or window; partial/failed reply rule; runtime-anchored estimates; conservative estimator; fallback trim announces the gap |
| Summary verification | `core/tests/unit/test_compaction.py` | LAZIS suggestions attributed to the user are dropped; invented facts without a matching quote are dropped; out-of-range citations; people kept apart and dates kept with their event; replaced decisions not shown as current; uncertainty marked; malformed and truncated JSON (complete items salvaged) |
| Conversation storage | `core/tests/integration/test_conversation_storage.py` | v1 → v2 upgrade with an encrypted backup; failed later migration leaves data intact; `seq` and idempotency keys enforced; rollback leaves nothing; foreign keys and cascade; locked database → `database_busy`; no plaintext in the database, WAL, SHM or backups; corrupted pages → `database_corrupt`, file untouched |
| Conversation engine | `core/tests/integration/test_conversation_engine.py` | single and multi-turn; isolation; reopen after restart; cancel keeps the partial reply and later prompts mark it; failed reply excluded; runtime down / model missing refused before storing; shutdown → interrupted; crash leftover → interrupted; duplicate and busy refused; over-budget turn compacts first and keeps originals; idle compaction + pre-warm; failed compaction → announced trim; pre-warm makes the next turn warm; a turn waits for its own pre-warm; a turn preempts compaction; other runtime requests make the next turn cold; delete removes everything and evicts the runtime cache; rename and paging; on-demand compaction; **300-turn soak** without overflow |
| Conversation API security | `core/tests/security/test_conversation_api.py` | token on every endpoint; foreign Origin; validation before storage; duplicate submission; runtime down; isolation over HTTP; content never in logs or error payloads (including the failure path and titles); `database_busy` mapping; prepare and activity |
| UI conversations | `apps/desktop/ui/tests/unit/conversations.spec.ts` | reopen the most recent conversation; new conversation stored with the first message; switching; real backend stages; stop keeps the partial reply; refused message stays in the composer; Turkish errors; interrupted and failed replies labelled; inline rename; delete only after confirmation; paging; summary notice; runtime down; no browser-storage writes |
| UI ↔ real backend (opt-in live) | `backend.integration.spec.ts` with `LAZIS_TEST_MODEL` | persistent multi-turn conversation with the real model: recall of an earlier message, stop, rename, delete; the backend's log file never contains the conversation text |

Live measurements (not CI): `evals/runners/p3_conversation.py` (cold, warm and pre-warmed TTFT per scenario, runner memory, estimator error) and `evals/runners/p3_context_eval.py` (probe accuracy after compaction vs full history).

Rules that apply to these suites: synthetic data only; no test contacts another host (refused targets are TEST-NET-1 `192.0.2.1`, `2001:db8::/32` and the reserved `.invalid` TLD); destructive tests run only in temporary directories, never against a real profile.

