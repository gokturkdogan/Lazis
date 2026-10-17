-- 0001_system — Phase 1 foundation tables (lazis.db).
-- Forward-only. Never edit after it has been applied anywhere; add 0002_* instead.

CREATE TABLE app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
) STRICT;

-- Every write belongs to exactly one change set (MEMORY_ARCHITECTURE §6).
CREATE TABLE change_sets (
    id                    TEXT PRIMARY KEY,
    kind                  TEXT NOT NULL,
    actor                 TEXT NOT NULL CHECK (actor IN ('user', 'pipeline', 'import', 'system')),
    source_ref            TEXT,
    summary               TEXT NOT NULL,
    reverts_change_set_id TEXT REFERENCES change_sets(id),
    status                TEXT NOT NULL CHECK (status IN ('applied', 'partially_reverted', 'reverted')),
    created_at            TEXT NOT NULL
) STRICT;

-- Append-only version log; before/after JSON is purged on hard delete (tombstones keep ids).
CREATE TABLE history (
    target_table  TEXT NOT NULL,
    target_id     TEXT NOT NULL,
    version       INTEGER NOT NULL,
    change        TEXT NOT NULL,
    change_set_id TEXT NOT NULL REFERENCES change_sets(id),
    before_json   TEXT,
    after_json    TEXT,
    at            TEXT NOT NULL,
    PRIMARY KEY (target_table, target_id, version)
) STRICT;
CREATE INDEX ix_history_change_set ON history(change_set_id);

-- UI-editable preferences (validated by the application before writing).
CREATE TABLE settings (
    key                   TEXT PRIMARY KEY,
    value_json            TEXT NOT NULL,
    updated_at            TEXT NOT NULL,
    updated_change_set_id TEXT NOT NULL REFERENCES change_sets(id)
) STRICT;

-- Security-relevant events without personal content (SECURITY_MODEL §5.10).
CREATE TABLE audit_log (
    id            TEXT PRIMARY KEY,
    at            TEXT NOT NULL,
    category      TEXT NOT NULL,
    action        TEXT NOT NULL,
    actor         TEXT NOT NULL,
    target_refs   TEXT,
    change_set_id TEXT,
    outcome       TEXT NOT NULL CHECK (outcome IN ('success', 'failure', 'denied')),
    reason_code   TEXT,
    details_json  TEXT
) STRICT;
CREATE INDEX ix_audit_at ON audit_log(at);
