-- 0002_conversations — Phase 3: persistent conversations and context state (lazis.db).
-- Forward-only. Never edit after it has been applied anywhere; add 0003_* instead.
--
-- Conversation history is NOT personal memory (MEMORY_ARCHITECTURE): no facts are derived
-- from these rows in Phase 3. Rows are deleted, not flagged, when the user deletes a
-- conversation; ON DELETE CASCADE removes messages, context state and summaries with it.
-- Message content is never copied into `history` or `audit_log` (ADR-0010).

CREATE TABLE conversations (
    id               TEXT PRIMARY KEY,
    title            TEXT NOT NULL,
    title_source     TEXT NOT NULL CHECK (title_source IN ('auto', 'user')),
    model            TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    message_count    INTEGER NOT NULL DEFAULT 0 CHECK (message_count >= 0),
    last_seq         INTEGER NOT NULL DEFAULT 0 CHECK (last_seq >= 0),
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
) STRICT;
CREATE INDEX ix_conversations_updated ON conversations(updated_at DESC, id DESC);

-- One row per user or assistant turn. `seq` is the deterministic order inside a conversation
-- (assigned by the application inside the write transaction, never reused).
-- `client_id` is the client's idempotency key for a submitted user message: a retried
-- submission with the same key is detected instead of being stored twice.
-- `context_note` is the per-turn note (local date/time) rendered once at send time and stored,
-- so later prompts reproduce the exact same text (stable, cacheable history).
CREATE TABLE messages (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    seq              INTEGER NOT NULL CHECK (seq >= 1),
    role             TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content          TEXT NOT NULL,
    context_note     TEXT,
    status           TEXT NOT NULL
                     CHECK (status IN ('complete', 'streaming', 'cancelled', 'interrupted', 'failed')),
    client_id        TEXT UNIQUE,
    reply_to         TEXT REFERENCES messages(id) ON DELETE CASCADE,
    model            TEXT,
    token_count      INTEGER CHECK (token_count IS NULL OR token_count >= 0),
    token_source     TEXT CHECK (token_source IS NULL OR token_source IN ('runtime', 'estimate')),
    prompt_tokens    INTEGER,
    output_tokens    INTEGER,
    ttft_ms          REAL,
    total_ms         REAL,
    error_code       TEXT,
    created_at       TEXT NOT NULL,
    completed_at     TEXT,
    UNIQUE (conversation_id, seq)
) STRICT;
CREATE INDEX ix_messages_status ON messages(status) WHERE status = 'streaming';

-- Structured, regenerable summaries of a contiguous message range [from_seq, to_seq].
-- They never replace the original messages; `content_json` items cite message ids/seqs.
CREATE TABLE context_summaries (
    id               TEXT PRIMARY KEY,
    conversation_id  TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    version          INTEGER NOT NULL CHECK (version >= 1),
    from_seq         INTEGER NOT NULL CHECK (from_seq >= 1),
    to_seq           INTEGER NOT NULL,
    previous_id      TEXT REFERENCES context_summaries(id) ON DELETE SET NULL,
    status           TEXT NOT NULL CHECK (status IN ('active', 'superseded', 'invalidated')),
    content_json     TEXT NOT NULL,
    rendered         TEXT NOT NULL,
    token_count      INTEGER NOT NULL CHECK (token_count >= 0),
    token_source     TEXT NOT NULL CHECK (token_source IN ('runtime', 'estimate')),
    model            TEXT NOT NULL,
    prompt_version   TEXT NOT NULL,
    kept_items       INTEGER NOT NULL DEFAULT 0,
    dropped_items    INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    CHECK (to_seq >= from_seq),
    UNIQUE (conversation_id, version)
) STRICT;
CREATE INDEX ix_context_summaries_conv ON context_summaries(conversation_id, status);

-- Per-conversation context layout: which messages are sent verbatim, which summary precedes
-- them, and the runtime-measured token anchors used by the budget.
CREATE TABLE conversation_context (
    conversation_id   TEXT PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
    context_version   INTEGER NOT NULL CHECK (context_version >= 1),
    prompt_version    TEXT NOT NULL,
    strategy          TEXT NOT NULL CHECK (strategy IN ('full', 'summary_window', 'window_only')),
    window_start_seq  INTEGER NOT NULL CHECK (window_start_seq >= 1),
    summary_id        TEXT REFERENCES context_summaries(id) ON DELETE SET NULL,
    budget_tokens     INTEGER NOT NULL CHECK (budget_tokens > 0),
    anchor_seq        INTEGER,
    anchor_tokens     INTEGER,
    prefix_hash       TEXT,
    last_prompt_tokens INTEGER,
    updated_at        TEXT NOT NULL
) STRICT;
