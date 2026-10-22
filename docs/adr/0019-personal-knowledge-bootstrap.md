# ADR-0019: Personal knowledge bootstrap — analyse, show, approve, write once, undo safely (Phase 8)

- **Status:** Implemented in Phase 8 (2026-10-21); awaiting the owner's acceptance test and approval with [PHASE_8_REPORT.md](../PHASE_8_REPORT.md).
- **Related:** [ADR-0014](0014-personal-memory-store.md) (store, change sets), [ADR-0015](0015-learning-recall-and-model-trust.md) (learning, model trust), [ADR-0016](0016-entity-relationship-graph.md) (graph), [ADR-0017](0017-truthful-memory-claims.md) (claims), [ADR-0018](0018-namesakes-and-explicit-requests.md) (namesakes), [MEMORY_ARCHITECTURE.md](../MEMORY_ARCHITECTURE.md) Part P8, [KNOWLEDGE_GRAPH_DESIGN.md §10](../KNOWLEDGE_GRAPH_DESIGN.md).

## Context

The owner wants to give LAZIS a prepared profile — a Markdown, text or JSON file about themselves, the people in their life, their projects, preferences, habits, goals and events — without the assistant guessing or silently changing what it already knows. The governing order is the brief's: analyse → validate → resolve identities → compare with memory → show → approve → write atomically → keep it undoable. Accuracy beats quantity; the user's approval beats the model's confidence; not writing beats writing to the wrong person.

What existed: a Phase 6 importer (`memory/importer.py`) with a fixed JSON shape (predicate keys), text read by the extraction model in one synchronous request (≤ 8,000 characters, no relationships, quotes dropped), one preview stored as an `import_batch` inbox item, items pre-selected in the UI, and no undo — memory tables are tracked in `history` but were never revertible.

## Decision

### 1. A bootstrap pipeline in its own package (`lazis.bootstrap`), state in the encrypted database

```
file content (UI reads it; no path crosses the API)
 → files.read: size limit, UTF-8/UTF-16 check, NUL/binary refused, secrets redacted, sections
 → profile (JSON, deterministic) | extraction (Markdown/text, Gemma, section by section, background job)
 → analyze: proposed people (namesakes from the user's words), dependencies, classification
            against memory (new / exact / possible duplicate / conflict / temporal update /
            ambiguous entity / insufficient evidence / excluded)
 → preview: nothing approved by default; per item approve / reject / edit / hold,
            per person create / link / keep unresolved / reject, per conflict keep / update / both / defer
 → apply: one change set, one transaction, only approved items whose dependencies are approved
 → undo: a plan from the change set's history and the import's evidence, previewed, then one transaction
```

Migration `0006_bootstrap` adds `import_batches` (the import: status, file name, format, counts, change sets), `import_people` (proposed people and the user's decision), `import_items` (each proposed fact or relationship: payload, source section / excerpt / line, method, confidence, classification, decision, edited value, written ids) and `import_sections` (the redacted section text while analysing, deleted when the import is applied, discarded or cancelled). Drafts live only in the SQLCipher database; nothing is written to temporary files.

### 2. The file is untrusted data

The model sees it inside the learning instruction as data; instruction-like lines are dropped by the existing validation; approvals exist only as API calls from the user's own clicks — no text in a file can approve, write or change a rule. On top of the learning policy (shared with chat and measured on its gold sets), an import-only check (`analyze.directive`) excludes text that gives the assistant an order ("Sistem: … kaydet", "hepsini onayla", "bundan sonra kullanıcıya …"); such items are shown as excluded and cannot be approved, and an edited value goes through the same check. Secrets (password, PIN, key, card, IBAN, id number) are redacted line by line before the model or the draft sees them (Markdown/text), or replaced in the draft (JSON), and listed as excluded.

The file reaches the backend as bytes (base64) in one request; no path crosses the API. That one route (`POST /memory/bootstrap/analyze`) accepts a bounded body of 1.45 MB (the file limit is 1 MB); every other route keeps the normal request limit.

### 3. Extraction: the learning instruction, per section

Markdown is cut at headings (the heading path is the item's section), text at paragraphs, both into ≤ 1,400-character sections — one model call each, on the standalone system prompt (no conversation prefix), the primary trusted model only (Gemma; ADR-0015), as a background job in the shared runtime slot that a user turn preempts. Sections under different headings are **not** packed together: with one person's heading per section, validation drops a fact whose name is not in the section, which guards against facts landing on the wrong person; packing would weaken that for fewer calls.

Every item keeps the user's own quote (validated in the section) and its line. The import's output budget is 2,048 tokens (a profile line can be a fact; learning's 700 would cut dense sections). An answer cut off at the limit, or not valid JSON, is never counted: the section is read again as two halves (the heading line stays on both), the extra call is counted and the split listed in the warnings; a single line that still fails is marked failed and offered for an explicit retry. The import is never reported as complete with failed sections.

The model's predicate for a person is checked against its quote (import only): "Elif pilot" filed under family becomes occupation, "Ahmet mimar" filed under location becomes occupation, "Doğum günü 3 Nisan" becomes birthday; a place needs a locative or a residence verb; anything else becomes a plain note. Each correction is listed in the warnings. JSON (`schema_version` 1.0, or the Phase 6 shape) is mapped deterministically, with file-local ids for namesakes; a `facts` entry may carry `since`/`date`, which makes a change a temporal update.

### 4. People are proposals until the user decides

Each distinct person in the file (namesakes split by the user's words — Phase 7.2 `namesakes.stated`; the same person with several roles kept together) is a proposed person with its own id. The resolver suggests a stored match only when it is unique and compatible; otherwise the person is ambiguous. Default decision: none. Items about a person, and relationships with an end at a person, are writable only once that person is "create new" or "link existing"; "keep unresolved" and "reject" block them. Choosing a person re-validates its dependent items. A person the user creates although stored namesakes were shown is recorded as a different person from each of them (`memory_entity_distinctions`), so later chat does not merge them.

### 5. Existing memory is never changed silently

Single-valued facts that differ from what is stored are conflicts (or temporal updates when the file says it changed — "artık", "taşındı", a date). A single-valued relationship to a new person (a second spouse) is a conflict too. The user chooses: keep the old, update (the old becomes history), keep both with time, or defer. Exact duplicates write nothing new (approval adds the import's evidence only); possible duplicates are shown side by side.

### 6. One transaction, real counts

Apply runs in one `UnitOfWork` (kind `import`, source = import id): people, facts (`service.apply_one` with forced subjects and the conflict choice), relationships (`relationships.apply_one` with forced ends). The batch's status moves to `applied` inside the same transaction, so a second apply is refused. Every number shown (analysed, approved, written, updated, held, rejected, failed) is counted from what the transaction wrote, per item; each item also carries its save state (`save_succeeded`, `save_failed`, `save_cancelled`, `save_rejected`, `save_pending_approval`) derived from its result, never from its decision. Before writing, every approved item is classified again against the memory as it is now; if one became a conflict (said differently in chat meanwhile), nothing is written and the preview is refreshed. If the transaction fails, it is rolled back, the draft stays as it was, the failure is recorded (`apply_failed`, audit outcome `failure`) and trying again is the user's explicit choice.

### 7. Undo is a plan, not a delete by import id

For every row in the import's change set: a record the import created is removed only if it was not changed afterwards and has no evidence from any other source (otherwise it is kept and only the import's evidence goes); a record the import changed (superseded, ended) is restored only if nothing changed it since (otherwise the user decides); a person the import created is removed only if nothing else refers to it. "Changed afterwards" compares the record's content with the state the import left it in (not version numbers): a later import that was itself undone leaves the record unchanged. A replaced record whose replacement is kept is not restored (two current values would result): the user decides. The plan is shown first (remove / restore / keep / needs a decision), then applied in one transaction (kind `rollback`); records left to the user can be restored by an explicit choice in the same request; a second undo is a no-op.

### 8. Rejected stays rejected

A rejected fact whose subject is known gets a `rejected` suppression (background learning will not write it again; an explicit request still can). A re-import of the same file shows earlier rejections as such, never pre-approved. Cancelling an analysis stops its model call and deletes its draft.

### 9. Ambiguous people are not context (condition E, all recall)

Recall no longer brings the facts and relationships of namesakes the message does not tell apart (or of a name with an open "which one?" question); it brings only who they are, so the reply asks.

## Consequences

- Text import becomes a background job with progress and cancel; JSON stays immediate.
- A large file takes one model call per section, more when a section has to be split (measured in PHASE_8_REPORT §14).
- An analysis cut short by quitting the app is marked `interrupted` at the next start and resumed only when the user asks.
- A user turn during an import preempts it. Ollama sends no headers while it reads a long prompt, so the provider now cancels a request while waiting for them too, and a turn gives a preempted background job at most 2 s (`scheduler.PREEMPT_GRACE_S`) before stopping its task; the import runner takes that as a preemption and carries on. This also bounds the wait behind background learning (Phase 6). Measured: first token 4.1 s during an import (0.5 s idle) — the rest is re-reading the chat prefix the import's prompt evicted from the cache.
- The Phase 6 inbox `import_batch` path is kept for API compatibility but no longer used by the UI.
- Undo can leave records in place when they were confirmed or edited afterwards — by design.
