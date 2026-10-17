# LAZIS — Engineering Standards

> Status: Phase 0.1 (new document) · Last updated: 2026-10-17 · Applies to every implementation phase (P1–P15)
> Goal: a codebase that a **small team (or one developer with an AI assistant) can maintain for years**. Prefer the simplest thing that meets the requirement, and keep it consistent.

## 1. Principles

1. **Simple first.** Abstractions exist only at real boundaries: inference engines, STT/TTS engines, search providers, the storage driver, key access and the OS (audio, files). Everything else is plain modules and functions.
2. **Rule of three.** Generalize after the third concrete use, not before.
3. **No speculative infrastructure:** no microservices, event sourcing, ORM, plugin system, multi-tenancy, message broker or generic repository framework.
4. **Explicit over magic:** dependency injection through one container (`app/container.py`); no global mutable state; time via an injectable `Clock`; IDs via a ULID generator.
5. **Every behavior that matters is configured, versioned and testable:** thresholds, budgets, policies and lexicons live in config files, not in code.
6. **Truthful engineering:** no claim of a passing test, a met target or a measured number without the executed evidence.

## 2. Python (lazis-core)

| Topic | Standard |
|---|---|
| Version / env | Python 3.13 (`.python-version`), `uv` + `uv.lock`; `src/` layout |
| Formatting / lint | `ruff format` + `ruff check` (rules incl. `E,F,I,B,UP,SIM,RUF,ASYNC,S`), line length 100 |
| Typing | **pyright strict** (CI gate). No `Any` except at serialization boundaries, with a `# reason:` comment. `Protocol` for ports. **Pydantic v2** models at boundaries (API, config, LLM I/O, events); frozen `dataclass(slots=True)` for internal values |
| Async | One asyncio loop. No blocking I/O in the loop. CPU/GPU work in bounded executors. Every external call has an explicit timeout. Cancellation-safe code (`try/finally` around streams) |
| Errors | Typed hierarchy under `LazisError` (ARCHITECTURE §10). No bare `except`, no silent swallowing. User-facing errors carry Turkish **message keys**, not text |
| Logging | Stdlib logging with a JSON formatter and a mandatory redaction filter. Event-style messages (`log.info("memory.saved", memory_id=…, level="A")`). **Never log message, memory or document content** (§12) |
| Naming | Modules `snake_case`; classes `PascalCase`; private helpers prefixed `_`; one public API per module, exported in `__init__.py` |
| Docstrings | Public interfaces and non-obvious decisions only, explaining *why*. No restating of the code |
| SQL | Hand-written, parameterized SQL in repositories. No string interpolation of values. Queries live next to their repository |
| Strings | Turkish user-facing text lives in message catalogs (`locales/tr`) and persona/lexicon config, not in code |

## 3. TypeScript / Vue (UI)

| Topic | Standard |
|---|---|
| Compiler | `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`; `vue-tsc` in CI |
| Lint / format | ESLint (vue, typescript) + Prettier |
| Components | `<script setup lang="ts">`; components stay presentational; logic lives in Pinia stores and composables |
| API types | **Generated only** (OpenAPI → `openapi-typescript`, event JSON Schema → TS). No hand-written DTOs; CI fails on drift |
| State | One Pinia store per domain. High-frequency data (audio levels, token deltas) bypasses reactivity ([UI_ARCHITECTURE.md §3](UI_ARCHITECTURE.md)) |
| i18n | Every user-visible string goes through `vue-i18n` keys (`tr` primary) |
| 3D code | Isolated in `neural-core/` behind `StateVisual`. Explicit `dispose()` of geometries, materials and render targets. No allocations in the render loop |
| Accessibility | Keyboard reachable, ARIA live region for state, reduced-motion respected |

## 4. Rust (Tauri shell) boundaries

- **Allowed responsibilities only:** window and tray, global shortcuts, sidecar spawn and supervision, Keychain access, native dialogs (file/folder pickers), single-instance lock.
- **Not allowed:** domain logic, network calls, database access, parsing user data.
- Tauri commands are minimal and typed. Capabilities follow least privilege (no shell plugin, no broad fs scope). CSP is strict.
- `cargo fmt`, `clippy -D warnings`; no `unsafe` without a documented review.

## 5. Swift (lazis-audio, P13)
Audio I/O only (VPIO capture/playback, resampling, levels, devices). No ML, no business logic. The framing protocol is versioned (`HELLO`). Swift 6 strict concurrency. XCTest for protocol and device-change handling.

## 6. Module isolation and API versioning

- **`import-linter` contracts (CI gate):**
  - layered: interface → orchestration → domain → platform;
  - the domain DAG ([ARCHITECTURE.md §4](ARCHITECTURE.md));
  - only `security.egress` makes non-loopback HTTP calls (local inference adapters may call loopback only; research providers, including the local SearXNG, always go through the gateway);
  - only `storage` imports the SQLite driver;
  - only `graph` writes entity/alias/relationship/mention tables.
- Modules communicate through their public interfaces and domain types, never through each other's tables or internal classes.
- **External API:** `/api/v1`. Additive changes only within a version. Breaking changes need `/api/v2` with a deprecation window of at least one phase. OpenAPI and the event JSON Schema are generated, committed and diff-checked. Every WebSocket event carries `schema_version`.
- **Internal ports:** changing a port signature requires updating every adapter and the contract test suite in the same change.

## 7. Dependency management

A new dependency requires all of the following, recorded in the PR or commit message:
1. **Need:** what it replaces, and why the standard library or an existing dependency is insufficient.
2. **Health:** recent releases, active maintainers, issue response.
3. **License:** allowed per §8.
4. **Footprint:** size, native extensions, transitive dependencies.
5. **Pinning:** exact version in the lockfile (`uv.lock`, `pnpm-lock.yaml`, `Cargo.lock`, `Package.resolved`).
6. **An ADR** if it is a core dependency (storage, inference, audio, UI framework).

Updates are deliberate (a batch review per phase gate), with changelog review. `pip-audit`, `pnpm audit` and `cargo audit` run in CI (advisory for low-severity transitive issues).

## 8. Licensing policy

| Category | Rule |
|---|---|
| MIT, BSD-2/3, Apache-2.0, ISC, PSF, Zlib, Unlicense | Allowed |
| MPL-2.0 | Allowed if unmodified (file-level copyleft) |
| LGPL | Review required (dynamic linking only) |
| GPL / AGPL | **Not linked** into LAZIS processes. A separate, unmodified process is acceptable (e.g., SearXNG in Docker). PyMuPDF (AGPL) is rejected |
| Model licenses (Apache-2.0 models, Gemma terms, OpenRAIL-M, CPML, CC-BY-NC) | Recorded per model. Non-commercial licenses are acceptable **only** as optional candidates under the personal-use assumption, and are flagged |

`THIRD_PARTY_LICENSES.md` is generated per release (P15) from the lockfiles and the model manifest.

## 9. Testing standards

- The layout mirrors the source: `core/tests/{unit,integration,contract,security,perf}/…`; test names describe the behavior (`test_forget_removes_vectors_and_fts`).
- **Deterministic by default:** no network, a fixed `Clock`, seeded randomness, `FakeLLMProvider`, temp encrypted databases. Live-model tests are opt-in and never part of blocking CI.
- **Fixtures are fictional.** A CI scan rejects fixture or log content matching the user's bootstrap names or seeded secrets.
- **Coverage:**
  - line + branch coverage ≥ 90% for `learning.policy`, `security`, `storage`, `text`, `graph.resolver`, and the research permission/scrubber code (CI gate for these modules);
  - ≥ 75% elsewhere (guide).
- **Flaky tests are bugs:** quarantine within a day, fix before the phase gate.
- **Every bug fix adds a regression test.**
- **Integration tests use real SQLCipher, sqlite-vec and FTS5.** No mocking of the database.
- **E2E:** Playwright (WebKit) against the dev server with the fake backend, plus the manual Tauri smoke checklist.
- **Reporting:** the phase test report lists commands, pass/fail/skip counts, failures with explanations, eval metrics against thresholds, and known issues ([TESTING_STRATEGY.md §10](TESTING_STRATEGY.md)).

## 10. Configuration standards

- All thresholds, budgets, paths and model identifiers live in config ([ARCHITECTURE.md §11](ARCHITECTURE.md)). Pydantic schemas carry defaults and validation; an invalid config fails startup with a clear message.
- Keys are dotted `snake_case` namespaces (`learning.thresholds.high`, `research.mode`).
- Policy and lexicon files carry a `version` field and are **hash-stamped** into decisions. Changing them bumps the version and is noted in the changelog.
- No secrets in config files. Environment variables are for development and test overrides only.
- User-editable settings are validated, and changes to permission-relevant settings are audited.

## 11. Database migrations

- **Forward-only**, numbered SQL files per database track (`migrations/{lazis,documents,cache}/NNNN_name.sql`), with checksums recorded in `schema_migrations`. **Never edit an applied migration.**
- Each migration ships with a fixture DB at the previous version and a test that migrates it, plus a test from empty.
- Data migrations are separate numbered steps. Long ones run as resumable background jobs.
- An automatic backup precedes every migration run. "Downgrade" means restoring that backup (documented, tested).
- The schema descriptions in the docs are updated in the same change.

## 12. Structured logging and metrics

- JSON lines with these fields: `ts`, `level`, `event`, `module`, `turn_id`, `change_set_id`, `duration_ms`, `outcome`, `error_code`, plus event-specific IDs and counts.
- **Never logged:** message text, memory or document content, names, transcripts, queries (research queries go to the audit log, not to logs), keys, tokens.
- Levels: `debug` (off by default; content-free), `info` (lifecycle and decisions), `warning` (degradation), `error` (failed operation), `critical` (safe mode).
- Metrics (latencies, token counts, cache reuse, memory) go to `cache.db`, not logs. High-frequency events are sampled.
- Debug *content* logging is the separate, opt-in, auto-expiring mechanism ([SECURITY_MODEL.md §5.6](SECURITY_MODEL.md)).

## 13. Error handling

- Every external call (Ollama, audio helper, file parser worker, search provider, web fetch) has a timeout, a retry policy (or explicitly none) and a mapped error class.
- Errors carry `recoverable: bool` and a Turkish message key. The degradation matrix ([ARCHITECTURE.md §10](ARCHITECTURE.md)) is implemented, not improvised.
- Storage integrity errors switch to **read-only safe mode**. Nothing tries to "repair" personal data silently.

## 14. Performance benchmarking

- Benchmarks follow [BENCHMARK_PLAN.md](BENCHMARK_PLAN.md) and are reproducible via `just bench`.
- Changes touching hot paths (prompt assembly, retrieval, voice pipeline, render loop) run the relevant benchmark subset before merge.
- A regression of more than 10% on a gated metric blocks the phase gate unless accepted by an ADR.

## 15. Documentation updates

- Documentation changes ship **in the same change** as the code they describe.
- **ADRs** (`docs/adr/NNNN-title.md`): context, decision, alternatives considered, consequences, and evidence (links to reports). Required for technology, schema-principle and policy decisions.
- Each module has a short `README.md`: purpose, public interface, invariants.
- `CHANGELOG.md` is updated per phase. Docs and code are in English; user-facing text is in Turkish.

## 16. Reproducible environments

- Pinned toolchains: `.python-version`, `uv.lock`, `rust-toolchain.toml`, `packageManager` (pnpm) in `package.json`, Node version file, Swift tools version.
- Pinned runtime: the Ollama version and model digests in `config/defaults.toml`, verified at startup.
- `just setup` is idempotent. `just doctor` prints an environment report (versions, digests, Ollama env, FileVault, disk, power state). No global installs are needed beyond the documented Homebrew tools.

## 17. Workflow

- One branch per phase (`phase/p3-conversation`), small focused commits, and a tag at each gate (`p3-done`).
- **Self-review checklist** before each commit series: tests executed and reported; docs and ADRs updated; no personal data; dependencies justified and license-checked; migrations tested; no content in logs.
- The definition of done is [ACCEPTANCE_CRITERIA.md §1](ACCEPTANCE_CRITERIA.md).
