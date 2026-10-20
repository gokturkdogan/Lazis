-- 0004_memory — Phase 6: personal memory, people and projects (lazis.db). ADR-0014.
-- Forward-only. Never edit after it has been applied anywhere; add 0005_* instead.
--
-- Additive only: no existing row is read, changed or deleted. Conversation history stays
-- the source; memories are a separate, smaller layer derived from it (with evidence links),
-- from explicit commands, user edits and imports. Content lives only in this encrypted
-- database; audit_log/history carry ids and codes, never memory text.

-- People, projects and other things the user talks about. The user is not a row: a memory
-- with subject_id NULL is about the user.
CREATE TABLE memory_entities (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL CHECK (kind IN ('person', 'project', 'organization', 'place', 'thing')),
    name          TEXT NOT NULL,
    name_key      TEXT NOT NULL,              -- folded, suffix-free (lazis.memory.text.name_key)
    relation      TEXT,                       -- to the user, as the user said it ("çocukluk arkadaşı")
    relation_key  TEXT,
    description   TEXT,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'merged')),
    merged_into   TEXT REFERENCES memory_entities(id),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
) STRICT;
CREATE INDEX ix_memory_entities_key ON memory_entities(name_key, status);
CREATE INDEX ix_memory_entities_kind ON memory_entities(kind, status, updated_at);

CREATE TABLE memory_entity_aliases (
    entity_id  TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
    alias      TEXT NOT NULL,
    alias_key  TEXT NOT NULL,
    PRIMARY KEY (entity_id, alias_key)
) STRICT;
CREATE INDEX ix_memory_aliases_key ON memory_entity_aliases(alias_key);

-- One remembered statement. Superseded and retracted rows are kept for history ("eskiden"),
-- never used as current knowledge. Forgetting deletes rows (and their FTS entries).
CREATE TABLE memories (
    id                    TEXT PRIMARY KEY,
    kind                  TEXT NOT NULL,
    subject_id            TEXT REFERENCES memory_entities(id) ON DELETE CASCADE,
    predicate             TEXT NOT NULL,
    value                 TEXT NOT NULL,
    value_key             TEXT NOT NULL,
    content               TEXT NOT NULL,      -- canonical Turkish sentence
    keywords              TEXT NOT NULL DEFAULT '',
    status                TEXT NOT NULL CHECK (status IN ('active', 'superseded', 'retracted')),
    origin                TEXT NOT NULL
                          CHECK (origin IN ('stated', 'requested', 'confirmed', 'imported', 'user_edit', 'inferred')),
    confidence            REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    importance            REAL NOT NULL DEFAULT 0.5 CHECK (importance >= 0 AND importance <= 1),
    sensitivity           TEXT NOT NULL DEFAULT 'normal' CHECK (sensitivity IN ('normal', 'personal', 'sensitive')),
    sensitivity_category  TEXT,
    event_time            TEXT,
    valid_from            TEXT,
    valid_to              TEXT,
    supersedes_id         TEXT REFERENCES memories(id) ON DELETE SET NULL,
    conflict_state        TEXT NOT NULL DEFAULT 'none' CHECK (conflict_state IN ('none', 'pending')),
    recall_count          INTEGER NOT NULL DEFAULT 0,
    last_recalled_at      TEXT,
    change_set_id         TEXT NOT NULL REFERENCES change_sets(id),
    version               INTEGER NOT NULL DEFAULT 1,
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
) STRICT;
CREATE INDEX ix_memories_subject ON memories(subject_id, predicate, status);
CREATE INDEX ix_memories_status ON memories(status, kind, updated_at);

-- Where a memory came from (a user message, an import, an edit, a confirmation).
CREATE TABLE memory_evidence (
    id               TEXT PRIMARY KEY,
    memory_id        TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    source_type      TEXT NOT NULL CHECK (source_type IN ('message', 'import', 'user_edit', 'confirmation')),
    source_ref       TEXT,                    -- message id for 'message'
    quote            TEXT,                    -- verbatim span of the user's own words
    created_at       TEXT NOT NULL
) STRICT;
CREATE INDEX ix_memory_evidence_memory ON memory_evidence(memory_id);
CREATE INDEX ix_memory_evidence_source ON memory_evidence(source_ref);

-- Full-text index over folded text (memory sentence, keywords, subject name and aliases,
-- predicate label). Contentless with real deletes: forgetting removes the terms
-- (rowid = memories.rowid; maintained by lazis.memory.repository).
CREATE VIRTUAL TABLE memory_fts USING fts5(
    body, content='', contentless_delete=1, tokenize='unicode61 remove_diacritics 2'
);

-- Decisions LAZIS must not take alone: which person is meant, a contradiction, a sensitive
-- fact, a destructive bulk forget, an import preview. Pending candidates live here, not in
-- `memories`, so they are never retrieved as knowledge.
CREATE TABLE memory_inbox (
    id                TEXT PRIMARY KEY,
    type              TEXT NOT NULL
                      CHECK (type IN ('ambiguous_entity', 'conflict', 'sensitive', 'destructive', 'import_batch')),
    status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    summary           TEXT NOT NULL,
    payload_json      TEXT NOT NULL,
    conversation_id   TEXT,
    source_message_id TEXT,
    created_at        TEXT NOT NULL,
    resolved_at       TEXT,
    resolution        TEXT
) STRICT;
CREATE INDEX ix_memory_inbox_status ON memory_inbox(status, created_at);

-- Durable extraction queue: one job per user message, survives restarts, never duplicated.
CREATE TABLE memory_jobs (
    id               TEXT PRIMARY KEY,
    user_message_id  TEXT NOT NULL UNIQUE REFERENCES messages(id) ON DELETE CASCADE,
    conversation_id  TEXT NOT NULL,
    model            TEXT NOT NULL,
    status           TEXT NOT NULL
                     CHECK (status IN ('queued', 'running', 'done', 'skipped', 'deferred', 'failed')),
    attempts         INTEGER NOT NULL DEFAULT 0,
    last_error       TEXT,
    result_json      TEXT,                    -- counts only
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
) STRICT;
CREATE INDEX ix_memory_jobs_status ON memory_jobs(status, created_at);

-- Forgotten or rejected knowledge must not be re-learned automatically. Keyed by an HMAC of
-- (subject, predicate, value) — or (subject, predicate, '*') for "forget his job" — never text.
CREATE TABLE memory_suppressions (
    fingerprint  TEXT PRIMARY KEY,
    subject_id   TEXT,
    predicate    TEXT,
    reason       TEXT NOT NULL CHECK (reason IN ('forgotten', 'rejected')),
    created_at   TEXT NOT NULL
) STRICT;
CREATE INDEX ix_memory_suppressions_subject ON memory_suppressions(subject_id, predicate);
