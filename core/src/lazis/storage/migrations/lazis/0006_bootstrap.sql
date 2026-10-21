-- 0006_bootstrap — Phase 8: personal knowledge bootstrap (lazis.db). ADR-0019.
-- Forward-only. Never edit after it has been applied anywhere; add 0007_* instead.
--
-- An import is analysed into proposed people and proposed items, shown to the user, and only
-- what the user approves is written — in one change set. Drafts live here, in the encrypted
-- database, never in files. Section text is kept only while analysing (NULL afterwards).

CREATE TABLE import_batches (
    id                  TEXT PRIMARY KEY,                 -- the import_id
    status              TEXT NOT NULL CHECK (status IN
                          ('analyzing', 'ready', 'failed', 'cancelled', 'applied', 'undone',
                           'discarded')),
    file_name           TEXT NOT NULL,
    format              TEXT NOT NULL CHECK (format IN ('markdown', 'text', 'json')),
    content_hash        TEXT NOT NULL,                    -- sha256 of the decoded text
    size_bytes          INTEGER NOT NULL,
    sections_total      INTEGER NOT NULL DEFAULT 0,
    sections_done       INTEGER NOT NULL DEFAULT 0,
    sections_failed     INTEGER NOT NULL DEFAULT 0,
    model               TEXT,
    model_calls         INTEGER NOT NULL DEFAULT 0,
    error               TEXT,                             -- an error code, never content
    warnings_json       TEXT NOT NULL DEFAULT '[]',       -- validation notes (paths, counts)
    counts_json         TEXT NOT NULL DEFAULT '{}',       -- what apply / undo really did
    effects_json        TEXT NOT NULL DEFAULT '{}',       -- ids apply created outside history
    apply_change_set_id TEXT REFERENCES change_sets(id),
    undo_change_set_id  TEXT REFERENCES change_sets(id),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    applied_at          TEXT,
    undone_at           TEXT
) STRICT;
CREATE INDEX ix_import_batches_created ON import_batches(created_at);
CREATE INDEX ix_import_batches_hash ON import_batches(content_hash);

CREATE TABLE import_sections (
    import_id   TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    idx         INTEGER NOT NULL,
    heading     TEXT NOT NULL DEFAULT '',
    first_line  INTEGER NOT NULL,
    body        TEXT,                                     -- redacted text; NULL when done with
    result_json TEXT,                                     -- the validated model answer
    status      TEXT NOT NULL CHECK (status IN ('pending', 'done', 'failed')),
    attempts    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (import_id, idx)
) STRICT;

CREATE TABLE import_people (
    id             TEXT PRIMARY KEY,
    import_id      TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    seq            INTEGER NOT NULL,
    name           TEXT NOT NULL,
    kind           TEXT NOT NULL,
    relation       TEXT,                                  -- the user's words for them
    description    TEXT,
    match          TEXT NOT NULL CHECK (match IN ('new', 'existing', 'ambiguous')),
    options_json   TEXT NOT NULL DEFAULT '[]',            -- stored entities that could be them
    suggested_id   TEXT,                                  -- a unique compatible stored match
    note           TEXT,                                  -- why it is ambiguous
    decision       TEXT NOT NULL DEFAULT 'pending' CHECK (decision IN
                     ('pending', 'create', 'link', 'unresolved', 'reject')),
    link_id        TEXT,                                  -- decision 'link': the entity
    entity_id      TEXT,                                  -- after apply
    source_section TEXT NOT NULL DEFAULT '',
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
) STRICT;
CREATE INDEX ix_import_people_import ON import_people(import_id, seq);

CREATE TABLE import_items (
    id              TEXT PRIMARY KEY,
    import_id       TEXT NOT NULL REFERENCES import_batches(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('fact', 'relationship')),
    category        TEXT NOT NULL,
    payload_json    TEXT NOT NULL,                        -- the proposed fact or relationship
    subject_ref     TEXT,                                 -- facts: 'user' or an import_people id
    source_ref      TEXT,                                 -- relationships: 'user' or a person id
    target_ref      TEXT,
    source_section  TEXT NOT NULL DEFAULT '',
    source_excerpt  TEXT,
    source_line     INTEGER,
    method          TEXT NOT NULL CHECK (method IN ('json', 'gemma')),
    confidence      REAL NOT NULL,
    classification  TEXT NOT NULL,
    existing_json   TEXT NOT NULL DEFAULT '[]',           -- stored values it repeats or contradicts
    note            TEXT,
    decision        TEXT NOT NULL DEFAULT 'pending' CHECK (decision IN
                      ('pending', 'approve', 'reject', 'hold')),
    resolution      TEXT CHECK (resolution IN ('keep_old', 'update', 'keep_both')),
    edited_value    TEXT,
    result          TEXT,                                 -- after apply
    result_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
) STRICT;
CREATE INDEX ix_import_items_import ON import_items(import_id, seq);
