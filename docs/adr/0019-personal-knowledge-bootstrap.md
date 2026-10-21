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

The model sees it inside the learning instruction as data; instruction-like lines are dropped by the existing validation; approvals exist only as API calls from the user's own clicks — no text in a file can approve, write or change a rule. Secrets (password, PIN, key, card, IBAN, id number) are redacted before the model or the draft sees them and listed as excluded.

### 3. Extraction: the learning instruction, per section

Markdown is cut at headings (the heading path is the item's section), text at paragraphs, both into ≤ 1,400-character sections — one model call each, on the standalone system prompt (no conversation prefix), the primary trusted model only (Gemma; ADR-0015). Every item keeps the user's own quote (validated in the section) and its line. A section whose answer is not valid JSON is marked failed and offered for an explicit retry; the import is never reported as complete with failed sections. JSON (`schema_version` 1.0, or the Phase 6 shape) is mapped deterministically, with file-local ids for namesakes.

### 4. People are proposals until the user decides

Each distinct person in the file (namesakes split by the user's words — Phase 7.2 `namesakes.stated`; the same person with several roles kept together) is a proposed person with its own id. The resolver suggests a stored match only when it is unique and compatible; otherwise the person is ambiguous. Default decision: none. Items about a person, and relationships with an end at a person, are writable only once that person is "create new" or "link existing"; "keep unresolved" and "reject" block them. Choosing a person re-validates its dependent items.

### 5. Existing memory is never changed silently

Single-valued facts that differ from what is stored are conflicts (or temporal updates when the file says it changed — "artık", "taşındı", a date). The user chooses: keep the old, update (the old becomes history), keep both with time, or defer. Exact duplicates write nothing new (approval adds the import's evidence only); possible duplicates are shown side by side.

### 6. One transaction, real counts

Apply runs in one `UnitOfWork` (kind `import`, source = import id): people, facts (`service.apply_one` with forced subjects and the conflict choice), relationships (`relationships.apply_one` with forced ends). The batch's status moves to `applied` inside the same transaction, so a second apply is refused. Every number shown (analysed, approved, written, updated, held, rejected, failed) is counted from what the transaction wrote, per item.

### 7. Undo is a plan, not a delete by import id

For every row in the import's change set: a record the import created is removed only if it was not changed afterwards and has no evidence from any other source (otherwise it is kept and only the import's evidence goes); a record the import changed (superseded, ended) is restored only if nothing changed it since (otherwise the user decides); a person the import created is removed only if nothing else refers to it. The plan is shown first (remove / restore / keep / needs a decision), then applied in one transaction (kind `rollback`); a second undo is a no-op.

### 8. Rejected stays rejected

A rejected fact whose subject is known gets a `rejected` suppression (background learning will not write it again; an explicit request still can). A re-import of the same file shows earlier rejections as such, never pre-approved. Cancelling an analysis stops its model call and deletes its draft.

### 9. Ambiguous people are not context (condition E, all recall)

Recall no longer brings the facts and relationships of namesakes the message does not tell apart (or of a name with an open "which one?" question); it brings only who they are, so the reply asks.

## Consequences

- Text import becomes a background job with progress and cancel; JSON stays immediate.
- A large file takes one model call per section (measured in PHASE_8_REPORT §14).
- The Phase 6 inbox `import_batch` path is kept for API compatibility but no longer used by the UI.
- Undo can leave records in place when they were confirmed or edited afterwards — by design.
