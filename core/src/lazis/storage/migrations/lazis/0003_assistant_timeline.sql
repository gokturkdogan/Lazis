-- 0003_assistant_timeline — one assistant, one timeline, hidden technical sessions (ADR-0011).
-- Forward-only. Never edit after it has been applied anywhere; add 0004_* instead.
--
-- A `conversations` row is now a *technical session*: the unit the context engine works on
-- (window, summary, token anchor, prompt cache). The user sees one continuous timeline over
-- all sessions; exactly one session is active and receives new messages.
--
-- Existing data is kept as it is: no row is deleted, merged or rewritten, summaries and
-- context state are untouched. Only these additions are made:
--   * messages.timeline_seq — global, unique display order. Existing messages are numbered
--     session by session (sessions ordered by their last activity, then id; messages by their
--     per-session seq), so earlier parallel conversations stay as contiguous blocks instead of
--     being interleaved by timestamp. The most recently used session comes last.
--   * messages.channel — how a message entered LAZIS ('text' now; 'voice' later, P13).
--   * conversations.status — the most recently updated session stays 'active', all others
--     become 'archived' (closed sessions; still shown in the timeline). A partial unique
--     index guarantees at most one active session.

ALTER TABLE messages ADD COLUMN timeline_seq INTEGER CHECK (timeline_seq IS NULL OR timeline_seq >= 1);
ALTER TABLE messages ADD COLUMN channel TEXT NOT NULL DEFAULT 'text' CHECK (channel IN ('text', 'voice'));

UPDATE messages
SET timeline_seq = numbered.n
FROM (
    SELECT m.id AS message_id,
           ROW_NUMBER() OVER (ORDER BY c.updated_at, c.id, m.seq) AS n
    FROM messages AS m
    JOIN conversations AS c ON c.id = m.conversation_id
) AS numbered
WHERE messages.id = numbered.message_id;

CREATE UNIQUE INDEX ux_messages_timeline_seq ON messages(timeline_seq);

UPDATE conversations SET status = 'archived';
UPDATE conversations SET status = 'active'
WHERE id = (SELECT id FROM conversations ORDER BY updated_at DESC, id DESC LIMIT 1);

CREATE UNIQUE INDEX ux_conversations_one_active ON conversations(status) WHERE status = 'active';
