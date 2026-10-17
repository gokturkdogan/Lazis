# LAZIS — Developer Guide

> Status: Phase 1 (foundation) + Phase 1.1 hardening + Phase 2 local inference (§12) · Last updated: 2026-10-17
> What exists today: an encrypted local backend, a Tauri desktop shell that owns the database key, and a Turkish status UI. There is **no AI, no conversation, no memory, no voice and no internet access** yet. Architecture: [ARCHITECTURE.md](ARCHITECTURE.md) · Security: [SECURITY_MODEL.md](SECURITY_MODEL.md) · Phase report (Turkish): [PHASE_1_REPORT.md](PHASE_1_REPORT.md).

## 1. Prerequisites

| Tool | Version used | Install |
|---|---|---|
| macOS on Apple Silicon | macOS 14+ (developed on 27.0.1) | — |
| Xcode Command Line Tools | — | `xcode-select --install` (provides `make`, `clang`) |
| uv | 0.13+ | `brew install uv` (uv downloads CPython 3.13 itself) |
| Node.js + pnpm | Node 24+, pnpm 10.28.2 | `brew install node pnpm` (or `corepack enable`) |
| Rust | stable ≥ 1.90 (developed on 1.99.1) | `rustup` + `rustup component add rustfmt clippy` |

Docker is **not** used and must not become a dependency.

## 2. Setup and everyday commands

```bash
make setup     # uv sync (core/.venv), pnpm install, cargo fetch
make dev       # desktop app in development (dev profile, Vite hot reload on :1420)
make build     # release bundle → apps/desktop/src-tauri/target/release/bundle/macos/LAZIS.app
make check     # every linter + every automated test (what "green" means)
make help      # all commands
```

| Command | What it runs |
|---|---|
| `make test-core` | pytest: unit, integration (real encrypted DB, real backend subprocesses), security |
| `make test-ui` | Vitest unit tests (stores, API client, components, Turkish strings vs backend error codes) |
| `make test-ui-integration` | the TypeScript API client against a real backend process |
| `make test-shell` | Rust unit tests + lifecycle tests against the real backend (in-memory key store) |
| `make test-keychain` | opt-in: one round trip with a dedicated item in your real login Keychain, deleted afterwards |
| `make lint` | ruff + ruff format, pyright strict, import-linter; vue-tsc; rustfmt + clippy `-D warnings` |
| `make api-schema` | regenerate `ui/src/api/openapi.json` and `schema.d.ts` after changing an API model (a test fails on drift) |
| `make audit` | pip-audit, pnpm audit, cargo audit (sends package names/versions to the advisory services) |
| `make spike-storage` | SPK-04/05 storage benchmark ([ADR-0003](adr/0003-storage-driver-and-encryption.md)) |

The backend's virtualenv must exist (`make setup`) before the app or the shell tests can start the backend.

## 3. Repository layout

See [ARCHITECTURE.md §13.1](ARCHITECTURE.md). In short: `core/` is the Python backend (`lazis-core`), `apps/desktop/src-tauri/` the Rust shell, `apps/desktop/ui/` the Vue UI, `docs/` the blueprint and ADRs.

## 4. How the pieces start and stop

```
LAZIS.app (Rust)                                   lazis-core (Python, under sandbox-exec)
 ├─ resolve profile (default | dev | LAZIS_PROFILE); read FileVault state (fdesetup)
 ├─ Keychain: load key  ── missing & no DB → generate, store, read back
 │                      └─ missing & DB exists → needs_recovery (UI asks for the recovery code)
 ├─ spawn  sandbox-exec -p sandbox/backend.sb  python -I -m lazis serve
 │         --stdin-secrets --require-os-sandbox …     → close descriptors inherited from the shell
 │         (cleared environment)                      → verify the OS network sandbox (else FATAL)
 ├─ stdin  {"version":1,"session_token":…,"db_key":…}\n   → reads secrets (10 s timeout)
 │  (stdin stays open = lifeline)                          → data-directory lock (flock)
 │                                                          → roll back an interrupted restore, if any
 │                                                          → open SQLCipher DB, verify encryption,
 │                                                            pre-migration backup, migrate
 ├─ stdout ← LAZIS_READY {"port":…,"pid":…}   or  LAZIS_FATAL {"code":…} (exit 3)
 ├─ UI gets {port, token} via the backend_connection command / connection event
 └─ quit: close stdin → backend checkpoints WAL, writes audit, releases lock, exits
          (SIGTERM after 7 s, SIGKILL after 3 s more; child always reaped)
```

If the shell dies without cleanup, the pipe closes and the backend shuts itself down; a parent-PID watcher is a second guard. Ports are chosen by the OS (`port=0`), so there are no conflicts.

The backend refuses to start other programs and to open sockets to non-loopback addresses (application guard), and — when started by the shell — cannot reach another host at all (OS sandbox, [ADR-0009](adr/0009-backend-network-sandbox.md)). Never add code that needs either; P12 research will run in a separate helper.

Running the backend alone (tests do this): `cd core && uv run python -m lazis serve --stdin-secrets --data-dir /tmp/x --log-dir /tmp/x` and write the secrets JSON line to stdin. Without `--stdin-secrets` it refuses to start. `uv run python -m lazis check-driver` prints the SQLCipher version; `uv run python -m lazis openapi` prints the API schema.

## 5. Profiles, files and the Keychain

| | `default` (release builds) | `dev` (debug builds, `make dev`) |
|---|---|---|
| Data | `~/Library/Application Support/LAZIS/data.noindex/` | `~/Library/Application Support/LAZIS/dev/data.noindex/` |
| Logs | `~/Library/Logs/LAZIS/{core,desktop}.log` | `~/Library/Logs/LAZIS/dev/…` |
| User config (optional) | `~/Library/Application Support/LAZIS/config.toml` | `…/LAZIS/dev/config.toml` |
| Desktop state | `…/LAZIS/desktop-state.json` (recovery acknowledged?) | `…/LAZIS/dev/desktop-state.json` |
| Keychain | service `com.lazis.app`, account `database-key-v1` | account `database-key-v1-dev` |

`LAZIS_PROFILE=<name>` (`[a-z0-9-]{1,32}`) selects another isolated profile — useful for trying a fresh install without touching your data. Remove such a profile with:

```bash
security delete-generic-password -s com.lazis.app -a database-key-v1-<name>
rm -rf ~/Library/Application\ Support/LAZIS/<name> ~/Library/Logs/LAZIS/<name>
```

Never delete the Keychain item of a profile whose data you want to keep unless you have its recovery code.

`LAZIS_CORE_DIR` points debug builds at another backend checkout; release builds always use the repository's `core/` (an embedded runtime is a packaging-phase task).

## 6. Database, migrations and change sets

- One encrypted database `lazis.db` (SQLCipher 4, WAL, `secure_delete`, `foreign_keys`). All access goes through `storage/` on a single DB thread (`Database.run` / `run_sync`). Only `storage/driver.py` imports `sqlcipher3`.
- **Opening:** driver check (`cipher_version`) → refuse a plaintext file → key → wrong key = `database_key_invalid` → pragmas → migrate → header must not be plaintext → permissions 0600 → `quick_check` + `cipher_integrity_check`.
- **Migrations:** `core/src/lazis/storage/migrations/lazis/NNNN_name.sql`, contiguous numbers, forward only, each applied atomically, checksums recorded in `schema_migrations`. A changed or unknown applied migration stops startup (`migration_failed`). Before pending migrations run on an existing database, an encrypted snapshot is taken into `data.noindex/backups/` (retention 10). Add a migration by adding the next file — never edit an applied one.
- **Change sets:** write user-visible data inside `UnitOfWork(conn, actor=…, kind=…)`; call `snapshot()` before and `record()` after each change. `revert_change_set()` restores earlier versions and reports conflicts instead of overwriting later edits. Only tables listed in `REVERTIBLE_TABLES` take part (P1: `settings`). Conversation tables (P3) deliberately do not: `history` would keep a copy of every message after the user deletes the conversation ([ADR-0010](adr/0010-conversation-persistence-and-context.md)).
- **Backups:** `create_snapshot` (`sqlcipher_export` into an encrypted, durable, verified file + atomically written SHA-256 manifest; nothing left behind on failure) and `verify_snapshot` (key, `quick_check`, `cipher_integrity_check`, LAZIS schema, optional max schema version).
- **Restore:** `restore_snapshot(snapshot, db_path, key)` takes the data-directory lock (fails with `instance_already_running` while any process has the DB open), requires the manifest, stages and re-verifies a copy, writes a durable journal, moves the current DB and its `-wal`/`-shm` aside, installs, verifies and commits by marking the journal `committed`; the old files then go to `backups/pre-restore-<stamp>/` (last 3 kept). Failures roll back; the next `open_storage` rolls back an uncommitted restore and finishes a committed one, following the journal. The `fault=` argument is a test seam for failure injection. Details and evidence: [ADR-0003, Amendment 1](adr/0003-storage-driver-and-encryption.md).

## 7. Keys and recovery

- The key is 32 random bytes, generated once by the shell and kept in the Keychain. It is never written to disk, argv, environment or logs.
- On first run the UI shows a blocking dialog. The recovery code (`LZR1-XXXXX-…`, 58 characters) appears only when the user presses "Kodu göster"; "Devam et" needs the "I saved it" tick. Until then the dialog returns on every launch.
- If the Keychain item disappears while a database exists, the app shows the restore panel. A correct code reopens the database and re-stores the key; a code for another database is refused and nothing is stored.
- **Development note:** debug and release builds are ad-hoc signed. The Keychain binds the item's access to the binary's signature, so after a rebuild macOS may ask once whether LAZIS may use its Keychain item ("Always Allow" answers it). A stable signing identity removes this later.

## 8. Local API

Base `http://127.0.0.1:{port}/api/v1`; every request needs `Authorization: Bearer <token>`, `Host: 127.0.0.1:{port}` and, from a browser context, an allowed `Origin` (`tauri://localhost`; `http://localhost:1420` only in development). Endpoints: `GET /health`, `/app/info`, `/system/status`, `/settings`. Errors: `{"error": {"code", "message" (Turkish), "recoverable", "request_id"}}`. The UI translates `code` with `ui/src/i18n/tr.ts`; a test checks that every backend code has a Turkish string.

## 9. Logs and troubleshooting

- `core.log` is JSON lines (`event` + fields); `desktop.log` is the shell's log. Both rotate and both pass through redaction; neither should ever contain a token, a key, a recovery code or personal content. If you find one, treat it as a security bug.
- The Diagnostics tab shows recent connection events and error codes; Settings shows the effective (read-only) configuration.

| Symptom (code) | Cause / fix |
|---|---|
| `backend_not_found` | `core/.venv` missing → `make setup` |
| `instance_already_running` | another backend holds the profile's lock (e.g. a second debug build) → close it |
| `config_invalid` | `config.toml` has an unknown key or invalid value (field names are in `core.log`/stderr) |
| `keychain_denied` | the Keychain prompt was denied or the keychain is locked → unlock, then "Yeniden dene" |
| `database_key_missing` / `database_key_invalid` | the Keychain item is gone or does not match → enter the recovery code |
| `encryption_unavailable` | the `sqlcipher3` wheel is not the SQLCipher build → `make setup` again |
| `network_sandbox_unavailable` | `/usr/bin/sandbox-exec` is missing or the profile did not take effect; the backend is never run without it (see ADR-0009) |
| `restore_failed` | a restore was rejected or rolled back; the previous database is unchanged (details in `core.log`) |
| FileVault "Kapalı" in the privacy card | disk encryption is off: SQLCipher still protects the database, but logs, swap and other files are not encrypted at rest → enable it in System Settings › Privacy & Security |

## 10. Rules worth repeating

- Synthetic data only in tests and spikes; never real personal information.
- No network access from the backend (the network guard enforces it); no model downloads before P2 and only with the owner's approval.
- Don't add plugins or permissions to the Tauri capability without a security review; the webview must never receive the database key.
- Run `make check` before considering anything done, and report tests that were not run as not run.

## 11. Known limitations (Phase 1)

- The release app runs the backend from the repository's `core/.venv`; it is not yet a self-contained, signed, notarized app (packaging phase).
- No automatic backend restart (manual "Yeniden dene"); tray and auto-restart are P4.
- The recovery code cannot be shown again after acknowledgement (re-display behind Touch ID/password is a later feature).
- Keychain item uses the login keychain without the "this device only" class (needs a signed app with entitlements).
- `pnpm tauri dev` window can't be quit via AppleScript (it is not a bundle); use the window's close button or Ctrl+C in the terminal.
- The OS sandbox does not restrict *listening* addresses (Seatbelt limitation); loopback-only listening is enforced by the backend itself. `sandbox-exec` is deprecated by Apple; if it disappears the app fails closed (ADR-0009).
- Restore has no UI yet (library function, fully tested); a restore UI arrives with the memory UI (P6).
- Starlette prints a deprecation warning about `httpx` in the test client (tests only).

## 12. Local models (Phase 2)

```bash
make ollama-agent                         # Ollama as a LaunchAgent: OLLAMA_NO_CLOUD=1, 127.0.0.1:11434,
                                          # LLAMA_ARG_CACHE_RAM=2048 (override: LAZIS_PROMPT_CACHE_MIB=<MiB>)
scripts/ollama-agent.sh status            # agent state + the server's real OLLAMA_* environment
make model-pull MODEL=qwen3.5:9b-q4_K_M   # only tags listed in scripts/approved-models.txt
make bench MODEL=… [QUICK=1]              # performance (B1–B4, num_ctx, long context) → evals/reports/phase2/<model>/perf.json
make eval MODEL=…                         # Turkish quality, extraction, long conversation, think mode → quality.json
make blind MODELS="a b c"                 # blind pairwise rating page for the owner (evals/reports/phase2/blind/rate.html)
make test-ollama LAZIS_TEST_MODEL=…       # opt-in: real sandboxed backend + Ollama + model
```

- The app never downloads models. A missing model is an error (`llm_model_not_found`), not a download.
- The backend can reach only `127.0.0.1:11434`; `models.endpoint` must use that port.
- Context sizes are named profiles in config (`models.context_short|normal|long`); changing `num_ctx` reloads the model in Ollama (measured ≈ 1 s), so the app uses fixed sizes.
- The Phase 2 chat is ephemeral (UI memory only). Never add logging of prompts or answers; tests scan logs for a seeded prompt.
- Uninstall a model with `ollama rm <tag>`; restore Ollama's previous startup with `scripts/ollama-agent.sh uninstall`.


## 13. Conversations (Phase 3)

- **Using it:** the desktop app opens on the **Sohbet** tab: one assistant, one continuous timeline ([ADR-0011](adr/0011-single-assistant-timeline.md)). There is no conversation list, no "new chat", no renaming. Technical sessions exist only in the backend; a dashed line marks where the model's current context starts.
  - "Durdur" keeps the partial reply as *durduruldu*.
  - A reply cut by a crash or a shutdown is shown as *yarım kaldı*, never as complete.
- **Where it is stored:** the same SQLCipher database as everything else (`lazis.db`, migration `0002_conversations`).
  - Tables: `conversations`, `messages`, `context_summaries`, `conversation_context`.
  - The UI keeps text in memory only; nothing goes to browser storage. Logs never contain message text.
- **Code:** `core/src/lazis/conversation/`:
  - `engine.py`: turn lifecycle, compaction, pre-warm, maintenance loop;
  - `context.py`: prompt assembly and token budget;
  - `compaction.py`: summaries and the evidence check;
  - `scheduler.py`: the single runtime slot;
  - `repository.py`: SQL.

  Design and rationale: [ADR-0010](adr/0010-conversation-persistence-and-context.md).
- **Settings:** the `[conversation]` section of the config file, for example `compact_at_tokens`, `keep_recent_tokens`, `idle_compaction_delay_s` (default 5 s), `compaction_chunk_tokens`, `prewarm`. Defaults are in `config/model.py`; the validator refuses combinations where compaction could never shrink the context.
- **Inspecting the context:** `GET /api/v1/assistant` returns the active session, its strategy, window, summary, estimated tokens and cache state, and where it starts in the timeline. `GET /api/v1/timeline?before=&limit=` pages the timeline. Summaries can be invalidated from code (`engine.reset_context`); there is no route for it.
- **Measurements** (need Ollama and the model; throwaway encrypted database, deleted afterwards):
  - `uv run --project core python evals/runners/p3_conversation.py --model gemma4:12b-it-qat` — cold vs warm TTFT for each §6.4 scenario → `evals/reports/phase3/conversation_perf.json`;
  - `uv run --project core python evals/runners/p3_context_eval.py --model gemma4:12b-it-qat` — answers after compaction vs full history → `evals/reports/phase3/context_eval.json`;
  - `uv run --project core python evals/runners/p3_assistant.py --model gemma4:12b-it-qat` — single-assistant scenarios (opening, follow-ups, reopen, 20,000-message history, session change) → `evals/reports/phase3/assistant_perf.json`.
- **Live tests:** `LAZIS_TEST_MODEL=gemma4:12b-it-qat make test-ui-integration` runs one continuous conversation through the real backend: recall, stop, the same session after a backend restart, no text in logs.
