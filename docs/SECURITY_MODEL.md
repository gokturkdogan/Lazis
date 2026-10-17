# LAZIS — Security and Privacy Model

> Status: Phase 0.1 (revised) · Last updated: 2026-10-17
> LAZIS will hold one of the most sensitive datasets a person can have: their relationships, health, worries and plans. Security is a design constraint from **P1**, not a final-phase feature. P15 is an audit and hardening pass, not the point where protections are introduced.

## 1. Assets

| Asset | Sensitivity | Location |
|---|---|---|
| Personal memories, knowledge graph, conversations, change history | **Highest** | `lazis.db` (encrypted) |
| Audit log (incl. outbound research queries) | Medium–High | `lazis.db` (encrypted) |
| Document index (chunks of authorized files) | High | `documents.db` (encrypted, rebuildable) |
| Research cache, embedding cache, metrics | Medium | `cache.db` (encrypted, disposable) |
| Bootstrap files | Highest | user's file, imported into `lazis.db` |
| Voice reference clip / profile; the user's STT evaluation recordings | High (biometric-like) | `voices/`, private eval dir (never in the repository) |
| Logs | Low (by design) | `~/Library/Logs/LAZIS/` |
| Backups | Highest | `data.noindex/backups/` (encrypted) |
| Database key, recovery code, session token | Critical | Keychain / memory only / with the user |

## 2. Threat actors and assumptions

| Actor | In scope | Notes |
|---|---|---|
| Malicious web content (prompt injection, SSRF bait) | **Yes** | Primary active threat |
| Malicious or misleading content in authorized documents and third-party messages | **Yes** | Injection, false claims about people; trust caps + taint ([LOCAL_INGESTION_ARCHITECTURE.md](LOCAL_INGESTION_ARCHITECTURE.md)) |
| Local network attackers | **Yes** | Backend must be unreachable from the LAN |
| Other local macOS users / guest account | **Yes** | File permissions + database encryption |
| Device theft / lost laptop | **Yes** | FileVault (checked) + SQLCipher by default |
| Malware running as the user | Partial | Can't fully defend; encryption with a Keychain-held key raises the bar; no plaintext exports lying around |
| Model "misbehavior" (hallucinated memories, unsafe tool use) | **Yes** | Evidence verification, tool restrictions |
| Supply chain (malicious packages or model files) | **Yes** | Pinning, hashes, safetensors/GGUF only |
| Cloud/provider data collection | **Yes** | No cloud calls; `OLLAMA_NO_CLOUD=1`; egress gateway |
| Accidental disclosure by the user (sharing logs or screenshots) | Partial | Redacted logs, diagnostics bundle reviewed before export |

Assumptions: the owner's macOS account is trusted, macOS itself is not compromised, and the owner keeps FileVault enabled.

## 3. Trust boundaries

```mermaid
flowchart LR
    subgraph Trusted [Trusted: owner's processes]
      UI[Tauri UI] <-->|token + origin| CORE[lazis-core]
      CORE <-->|loopback| OLL[Ollama, NO_CLOUD]
      CORE <-->|UDS 0600| AUD[lazis-audio]
      CORE <--> DB[(lazis.db)]
    end
    subgraph SemiTrusted [Semi-trusted inputs]
      USER[User text/voice · T3–T5] --> CORE
      BOOT[Bootstrap YAML · T4] -->|schema validation + preview| CORE
      PDOC[User-authored documents · T2] -->|read-only, PathGuard, sandboxed parser| CORE
      ODOC[Other documents, third-party text · T1] -->|same + attribution| CORE
    end
    subgraph Untrusted [Untrusted]
      WEB[Web pages / search results · T0]
    end
    CORE -->|egress gateway only, permission engine| WEB
    WEB -->|quarantined reader, no tools| CORE
```

### 3.1 Trust classes for knowledge

Every piece of evidence carries a trust class. It drives the learning policy caps, contradiction tie-breaks and tool restrictions ([MEMORY_ARCHITECTURE.md §7](MEMORY_ARCHITECTURE.md)).

| Class | Source | May create personal knowledge? | Highest automatic level |
|---|---|---|---|
| **T5** | User edit, review approval, explicit confirmation of a question | Yes | A |
| **T4** | Explicit memory command; bootstrap items accepted in the preview | Yes | A (sensitive allowed, flagged) |
| **T3** | User statements in conversation (extracted) | Yes | A for low/medium risk; C for high risk |
| **T2** | Documents authored by the user (journal, personal notes) | Yes, capped | A for low risk; B for medium; C for high-impact social or family facts |
| **T1** | Other documents, third-party messages, LAZIS inferences | Project/reference knowledge only; personal claims → C | B (non-personal domain) |
| **T0** | Web research | **No** (separate cache; promotion only by explicit user action) | — |

Instructions found inside T0–T2 content are **data, never commands**. Only the user's own messages and the settings UI change LAZIS's behavior.

## 4. Data classification and policies

| Tier | Examples | Storage | Retrieval | Learning |
|---|---|---|---|---|
| `normal` | hobbies, food preferences, general facts | stored | normal | risk-based policy; usually automatic (Level A/B) |
| `personal` | family details, work, locations, routines | stored | normal; never sent to research unless the entity is public | risk-based policy (medium risk: A when confidence is high, else B) |
| `sensitive` | health, finances, religious or philosophical beliefs, political views, sexual life/orientation, legal or criminal matters, ethnicity, union/association membership, biometric data; intimate relationship details; third parties' sensitive info | stored with `sensitivity=sensitive` | only when topically relevant; never proactive unless allowed per item | **high risk → confirm first** (Level C), unless the user explicitly asked to remember it ([MEMORY_ARCHITECTURE.md §7](MEMORY_ARCHITECTURE.md)) |
| `restricted` | passwords, PINs, OTPs, national ID numbers (TC Kimlik No, checksum-validated), full card numbers (Luhn), IBANs, private keys, access tokens | **never stored**; detected and redacted in persisted messages | — | blocked + user is told why |

The sensitive categories mirror the "special categories of personal data" in Turkish data-protection law (KVKK Art. 6), used here as a sensible taxonomy. Purely personal and household processing by an individual is generally outside KVKK's scope, so this is a design reference, not a compliance claim.

**Third parties:** LAZIS stores information about people in the user's life. It keeps only what is relevant to the user's relationship with them, applies the same sensitivity tiers, and supports "forget everything about this person" with one action.

## 5. Controls by area

### 5.1 Storage and encryption

- Data under `~/Library/Application Support/LAZIS/` with directories `0700` and files `0600`. Permissions are verified at startup and fixed or warned about.
- **FileVault check** at startup (`fdesetup status`). If it is off, a persistent warning is shown. FileVault and database encryption are complementary.

**SQLite does not encrypt anything by itself.** Encryption requires **SQLCipher** (an SQLite fork with page-level AES-256 encryption), used through a Python binding (`sqlcipher3`) behind the storage connection factory.

| Topic | Design |
|---|---|
| **Default** | **Encrypted by default.** `lazis.db`, `documents.db`, `cache.db` and all backups are SQLCipher databases from the moment they are created |
| **When it is introduced** | **P1** builds the connection factory, key management and an encrypted `0001_system` database. No personal data exists before P3 (conversation persistence), so **real personal data is never stored unencrypted**. Development and test databases contain fictional data only |
| **Precondition** | Spike **SPK-05** (P1) must confirm that sqlite-vec and FTS5 load and work under SQLCipher, and measure the performance cost. If it fails, the user chooses (ADR): (a) block P3 until a fix is found, or (b) proceed temporarily on FileVault only, with the migration below |
| **Migration from an unencrypted DB** (only for the SPK-05 fallback) | `ATTACH` a new encrypted DB with the key → `SELECT sqlcipher_export('encrypted')` → verify (integrity check, row counts, checksums) → atomic swap → delete the old file. On APFS/SSD, deleting a file does not guarantee the old blocks are erased (copy-on-write, wear levelling), so FileVault is what protects any plaintext remnants. The user is told this |
| **Key** | 256-bit random data key, generated at first run. Stored as a Keychain generic password (service `com.lazis.app`, versioned account names `db-key-v1`, `v2`, …; accessibility: when unlocked, this device only). Never written to disk, argv, environment or logs |
| **Key access** | Through a `KeyProvider` port. P1–P3 (CLI phase): the Apple-signed `security` tool reads the Keychain item. P4+: the Tauri shell reads it and passes it to `lazis-core` over **stdin** at spawn. Both use the **same** Keychain item. The first access by a new binary triggers one macOS permission prompt ("Always Allow"). The exact item attributes are verified in SPK-05 |
| **Recovery code** | At setup, the key is shown once as a recovery code (grouped base32) for the user's password manager or a printout. The user must confirm they saved it, or explicitly decline and accept the risk |
| **Key loss** | Keychain intact → automatic. Keychain item lost but recovery code available → the code is entered at startup and the key is re-stored. **Both lost → the data is unrecoverable** (stated plainly at setup). There is no backdoor |
| **New Mac / restore** | "This device only" Keychain items do not migrate. Restoring a backup on another Mac requires the recovery code |
| **Key rotation** | `PRAGMA rekey` re-encrypts the live DB under a new key version. Backup manifests record their key version, and old key versions are kept in the Keychain until no retained backup needs them |
| **Backups** | Produced with `sqlcipher_export()` into an encrypted file, with the same key version as the live DB at that time. A restore verifies the manifest, opens with the recorded key version, then runs migrations forward |
| **Full-text and vector search** | SQLCipher encrypts **every page**, including FTS5 shadow tables and sqlite-vec `vec0` storage, so search works unchanged. Decrypted pages exist only in process memory. Cost: brute-force KNN reads every vector page; at 50k × 768 float32 (~150 MB) that means decrypting every page per query unless the page cache holds them. Mitigations: a page cache sized to hold the vector tables (`cache_size`), or int8 vectors with rescoring. **Measured in SPK-05**; the plaintext ≤ 30 ms KNN target is not assumed to hold |
| **Temporary data** | `PRAGMA temp_store=MEMORY`. Imports are parsed in memory. Exports are written only where the user chooses, with a warning |
| **Other** | `PRAGMA secure_delete=ON`. The WAL is checkpointed on shutdown. Optional memory-wiping settings of SQLCipher are evaluated in SPK-05 for their cost |

### 5.2 Local API exposure
- `lazis-core` binds **127.0.0.1** on a random port (or a UDS in a later hardening step). It never binds 0.0.0.0.
- Per-launch 256-bit token required on every request and WS connection; constant-time comparison.
- `Origin` / `Host` header validation (Tauri origin only) against DNS-rebinding and browser-based CSRF from websites running on the same machine.
- Ollama: `OLLAMA_HOST=127.0.0.1:11434`, `OLLAMA_ORIGINS` restricted, `OLLAMA_NO_CLOUD=1`.

### 5.3 Network egress
- **Single egress gateway** (`security.egress`): the only code path allowed to open non-loopback connections, and the mandatory path for all research traffic, including the local SearXNG container (which forwards queries to the internet). Local inference adapters may connect only to loopback (Ollama). A CI test monkey-patches `socket.connect` and fails on any other caller or destination.
- Policy: global kill switch (default **on = offline** until the user enables research), research permission modes and rules ([RESEARCH_ARCHITECTURE.md §1](RESEARCH_ARCHITECTURE.md)), domain allow/deny lists, HTTPS only, private IP blocking after DNS resolution, size and time limits.
- The gateway skeleton exists from **P1** in deny-all mode. A CI test asserts that no other code path opens sockets. Research capabilities arrive in P12.
- Every outbound request and every permission decision is recorded in `audit_log` (§5.10), including the exact scrubbed query text, and is visible in the UI.
- Model downloads happen only through the explicit setup command (`scripts/pull-and-verify-models`), never at runtime.
- Verification aid: users can confirm with a host firewall (e.g., LuLu or Little Snitch) that only expected connections occur. The docs list the expected hosts.

### 5.4 Prompt-injection and tool safety
- **Tool registry** with declared capabilities: `memory.read`, `memory.write`, `memory.forget`, `graph.read`, `research.search`, `documents.search` (P11). There are **no shell, code-execution, file-writing, email/messaging or purchasing tools**.
- **Permission matrix:**

| Tool | Clean turn | Turn with document text (semi-trusted) | Turn with web content (tainted) |
|---|---|---|---|
| `memory.read`, `graph.read`, `documents.search` | allowed | allowed | allowed |
| `memory.write` (remember/correct) | on direct user intent | only if the **user's own message** asks for it | disabled; the user must ask again in a later turn |
| `memory.forget` | on direct user intent (Level C if the target is ambiguous or the change is bulk) | same as left | disabled |
| `research.search` | per research mode | per research mode | disabled (no autonomous chaining) |
| Settings / permission changes | **never via tools**; UI or explicit user command only | never | never |

- **Taint tracking:** content from T0–T2 sources marks the turn. Background learning uses only the *user's* messages as evidence for personal facts. Document claims go through the ingestion trust caps.
- Quarantined reader for web content; quote verification; injection heuristics ([RESEARCH_ARCHITECTURE.md §6](RESEARCH_ARCHITECTURE.md)).
- Model outputs are always schema-validated before they affect state. A tool call naming an unregistered tool or carrying invalid arguments is rejected and logged.

### 5.5 Local file access (P11)
- Folders and files are authorized explicitly by the user (native picker or drag-and-drop) and stored as `sources` with a mandatory source class. LAZIS never scans anything else.
- **PathGuard:** canonicalize (`realpath`) and require the result to stay inside an authorized root, which blocks symlink escapes and `..` traversal. Hidden and system files and archives are excluded. Access is read-only, with size caps.
- Parsers run in a **sandboxed worker process** (resource limits).
- Ingested content goes to `documents.db`. Its trust class (T1/T2) caps what can become personal knowledge. Revocation removes the chunks and claims and retracts knowledge that only that source supported. Full design: [LOCAL_INGESTION_ARCHITECTURE.md](LOCAL_INGESTION_ARCHITECTURE.md).

### 5.6 Logging and diagnostics
- Structured JSON logs that by default contain **no message content, memory content, names or transcripts**. They contain only IDs, event types, durations, counts and error codes.
- The redaction layer runs on every log record (a known-entity-name scrubber plus pattern detectors) as a second line of defense.
- **Debug content logging** is opt-in, auto-expires after 24 h, shows a visible UI badge, and is written to a separate file purged on expiry.
- Log rotation: 10 files × 10 MB. Crash reports are local only.
- The diagnostics bundle (for troubleshooting) is shown to the user before saving.

### 5.7 Backups and recovery
- SQLCipher-encrypted snapshots with rotation ([MEMORY_ARCHITECTURE.md §19](MEMORY_ARCHITECTURE.md)). An integrity check and a SHA-256 manifest (including the key version) accompany each one.
- Restore is tested automatically (CI round trip) and manually before each release.
- Key loss = data loss. The recovery code (§5.1) is the only way to restore on a new Mac or after Keychain loss, and setup explains this trade-off.

### 5.8 Supply chain
- Lockfiles: `uv.lock`, `pnpm-lock.yaml`, `Cargo.lock`, `Package.resolved`. Dependencies are updated deliberately with changelog review.
- Model files: **safetensors / GGUF / ONNX / MLX only**. Pickle-based `.bin`/`.pt` are never loaded (no `torch.load` on untrusted files). Weights are pinned by Ollama digest or Hugging Face revision SHA plus a file SHA-256 and verified at startup.
- Audits: `pip-audit`, `pnpm audit`, `cargo audit` in CI (advisory, not blocking for transitive low severity).
- The Tauri content security policy (CSP) is strict: no remote scripts, `connect-src` only to the local core, `img-src` limited to local and data URIs.

### 5.9 Voice-specific
- No audio persisted by default. The microphone is active only in an explicit session or PTT, with an always-visible indicator.
- Voice cloning only from consented or synthetic references, with consent metadata stored.
- The user's evaluation recordings (P13) are stored in the encrypted data directory, outside the repository, and can be deleted from Settings.

### 5.10 Audit logging

`audit_log` in `lazis.db` (created in P1) records security-relevant events **without personal content**:

| Category | Events |
|---|---|
| `memory` / `graph` | deletions (counts and ids only), bulk changes, merges, splits, change-set rollbacks |
| `learning` | review-mode changes, policy version changes, learning-run rollbacks |
| `import` / `ingestion` | bootstrap apply and rollback; source authorization, revocation, re-index |
| `research` | every permission decision and outbound request: mode, query class, matched rule, decision, **exact scrubbed query text**, provider, hosts (no paths) |
| `security` | policy denials, tool rejections, failed auth or origin checks, key operations (creation, rotation, recovery-code use), FileVault warnings |
| `settings` / `backup` | network enable/disable, permission changes; backup creation, restore, purge |

Fields: `id, at, category, action, actor, target_refs, change_set_id, outcome, reason_code, details_json`. Retention is configurable (default 365 days; research query text 90 days). It is viewable and exportable in the System and Research log views. Audit rows are append-only from the application's point of view; the user can purge them explicitly.

## 6. Privacy UX commitments
1. **Visible state:** network on/off, mic active, off-record, research pending, learning activity.
2. **"Ne biliyorsun?"** always works: the user can ask or browse everything stored about them or anyone else.
3. **Reversible by default:** undo for memory edits, merges and imports.
4. **No dark patterns:** LAZIS never pressures the user to share more, and it never guilt-trips.

## 7. Security testing (summary)
Injection corpus (web and documents), egress-blocking tests, research permission-matrix tests, path-traversal fuzzing, sandboxed-parser tests, auth-token and origin tests, log-redaction tests (seeded secrets must never appear), restricted-data detector tests (TC Kimlik checksum, Luhn, IBAN), tool permission-matrix tests, audit completeness tests, and encryption checks: files unreadable without the key; the key never in argv, env or logs; recovery-code restore on a fresh Keychain; key rotation with old backups. See [TESTING_STRATEGY.md](TESTING_STRATEGY.md).

## 8. Residual risks (accepted, documented)
- Malware running as the user while LAZIS is unlocked can read data through the same APIs. This is mitigated only partially.
- Older backups retain deleted data until rotation (disclosed; a purge option is provided).
- Local models can still produce wrong or harmful advice. LAZIS is an assistant, not a professional (medical, legal or financial) authority, and says so when relevant.
