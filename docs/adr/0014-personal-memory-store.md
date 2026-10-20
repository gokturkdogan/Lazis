# ADR-0014: Personal memory store — one encrypted database, contentless full-text index, no embeddings (Phase 6)

- **Status:** Proposed for Phase 6 (2026-10-20). The owner reviews it with [PHASE_6_REPORT.md](../PHASE_6_REPORT.md).
- **Related:** [MEMORY_ARCHITECTURE.md](../MEMORY_ARCHITECTURE.md) Part P6 (as built), [ADR-0003](0003-storage-driver-and-encryption.md) (SQLCipher), [ADR-0010](0010-conversation-persistence-and-context.md) (change sets, history), [ADR-0015](0015-learning-recall-and-model-trust.md) (how memory is learned and used).

## Context

Phase 6 adds long-term personal memory: the user's profile, people, projects, experiences and preferences, with sources, validity, history, sensitive-data rules and a right to be forgotten. The brief requires:

- that it stays local and encrypted ("Ayrı, şifresiz bir kişisel hafıza veritabanı oluşturma");
- that it is fast at 10,000 records and beyond;
- that forgetting leaves nothing behind (active records, indexes, embeddings, derived summaries, caches);
- that dependencies stay minimal.

The Phase 0 design planned FTS5 plus sqlite-vec embeddings in the same database.

## Decisions

1. **Same SQLCipher database, migration 0004.** No second store, no second key.

   The tables are:
   - `memory_entities` (+ aliases);
   - `memories` (fact, provenance, validity, `supersedes_id` chain, sensitivity, conflict state);
   - `memory_evidence`;
   - `memory_inbox` (decisions waiting for the user);
   - `memory_jobs` (durable learning queue, one per user message);
   - `memory_suppressions` (keyed fingerprints of forgotten facts).

   The migration is taken with the existing pre-migration encrypted backup. A failure leaves the previous version untouched (tested with a half-applied 0004).

2. **Full-text search: FTS5, contentless with real deletes (`contentless_delete=1`).** The index stores no copy of the text, and deleting a row removes its terms. After a forget we run `optimize` so old segments do not keep terms.

   There are two columns:
   - `body`: the memory sentence, value and subject names;
   - `hints`: predicate label and search words, BM25 weight 0.2.

   Text is folded for Turkish (İ/ı casing, diacritics). Queries use proportional prefix terms ("bilgisayarımda" → `bilgisaya*`), and terms that match a large share of records are dropped.

3. **No embeddings in Phase 6.** Measured on this machine, recall over FTS5 plus entity matching takes well under a millisecond at 10,000 records (PHASE_6_REPORT §H). The gold set and the real sessions found the right memories.

   Embeddings would cost:
   - a new dependency (sqlite-vec plus an embedding model in Ollama);
   - memory and prefill time;
   - one more store that forgetting must purge.

   The design keeps the door open: a vector column can be added in a later migration, and forgetting already goes through one function.

4. **Change sets for every knowledge write; memory tables are history-tracked but not generically revertible.** The P1 `UnitOfWork` writes the change set and per-row history.

   The generic row restore (`INSERT OR REPLACE`) would give a memory a new rowid behind the contentless index, and it would cascade-delete its evidence. So memory tables are registered as `TRACKED_TABLES`, and a generic revert reports `table_not_revertible`. Undo happens through forget, edit and inbox decisions, which keep the index consistent.

5. **Forgetting is a hard delete plus a keyed suppression.** It removes:
   - rows of all statuses;
   - evidence;
   - FTS terms;
   - history content (a content-free tombstone stays);
   - related inbox items;
   - records merged into a deleted person.

   An HMAC-SHA256 fingerprint (key in `app_meta`, inside the encrypted database) stops background learning from re-learning the same fact or topic; an explicit request overrides it. Chat history and backups are separate layers: they are not touched, and LAZIS tells the user so.

6. **Restricted data never enters memory.** Credentials, tokens, IBAN (mod-97), TC kimlik (checksum), card numbers (Luhn) and instruction-like text are refused at every write path: learning, chat requests, manual add, edit and import.

   Health, finance, contact, street address and third parties' intimate matters are saved only with the user's approval: an inbox item, or an explicit request.

## Consequences

- One backup, one key, one migration path; the encrypted-at-rest guarantees of Phase 1 cover memory unchanged (tested: memory text never appears in the database, WAL or backup files).
- Search quality depends on Turkish prefix matching and the hint lists. Vowel narrowing ("yaşa-" → "yaşıyor") and synonyms are bridged by predicate hints, not by meaning. Embeddings remain the upgrade if real use shows misses.
- A generic "undo this change set" is not available for memory. The memory screen's edit and delete, and the inbox, are the correction paths.
- The suppression list grows with forgets; it holds only hashes and ids.
