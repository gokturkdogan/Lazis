-- 0008_adaptation — Phase 10B (lazis.db). Forward-only: never edit after it has been applied.
-- Phase 10B: the user's communication preferences (ADR-0022). Additive: three new tables,
-- nothing else changes; no existing row is read or rewritten.
--
-- communication_preferences: one row per style dimension the user or learning has touched.
--   explicit_value — what the user said ("Daha kısa cevap ver"); wins over everything.
--   learned_value  — what implicit signals moved it to (±0.1 a step), used only while no
--                    explicit value is set.
--   cleared_at     — the user removed the preference: signals before this never count again.
--   Values are text (levels "0"–"10", "sen"/"siz", "1"/"0").
CREATE TABLE communication_preferences (
    dimension            TEXT PRIMARY KEY CHECK (dimension IN (
                            'verbosity', 'elaboration', 'formality', 'humor',
                            'address', 'honorific')),
    explicit_value       TEXT,
    explicit_at          TEXT,
    explicit_message_id  TEXT,
    learned_value        TEXT,
    learned_at           TEXT,
    cleared_at           TEXT,
    updated_at           TEXT NOT NULL
) STRICT;

-- preference_signals: one implicit signal per (dimension, user message). Reprocessing the
-- same message can never add a second one (primary key). ``words`` is a keyed hash of the
-- folded message, so the same words in another message are the same statement (no text).
CREATE TABLE preference_signals (
    dimension        TEXT NOT NULL,
    message_id       TEXT NOT NULL,
    conversation_id  TEXT NOT NULL,
    direction        INTEGER NOT NULL CHECK (direction IN (-1, 1)),
    words            TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    PRIMARY KEY (dimension, message_id)
) STRICT;
CREATE INDEX preference_signals_by_time ON preference_signals (dimension, created_at);

-- preference_changes: why each value changed (explainable): an explicit instruction, a
-- learned step (with the signals behind it), a removal, an edit, or a refused request.
CREATE TABLE preference_changes (
    id           TEXT PRIMARY KEY,
    dimension    TEXT,
    source       TEXT NOT NULL CHECK (source IN (
                    'explicit', 'learned', 'cleared', 'user_edit', 'refused')),
    old_value    TEXT,
    new_value    TEXT,
    message_id   TEXT,
    detail       TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL
) STRICT;
CREATE INDEX preference_changes_by_time ON preference_changes (created_at);
