# ADR-0011: One assistant, one timeline, hidden technical sessions

- **Status:** Accepted for the Phase 3 addendum (2026-10-18). The owner reviews it with the updated Phase 3 report.
- **Supersedes:** the user-facing multi-conversation model of [ADR-0010](0010-conversation-persistence-and-context.md) §1–§2 (conversation list, new chat, rename, delete). Everything else in ADR-0010 stands: storage, turn lifecycle, prompt layout, token budget, compaction, scheduler, pre-warm and prompt-cache cap.
- **Related:** [MEMORY_ARCHITECTURE.md](../MEMORY_ARCHITECTURE.md), [VOICE_ARCHITECTURE.md](../VOICE_ARCHITECTURE.md), [PHASE_3_REPORT.md](../PHASE_3_REPORT.md) §13.

## Context

LAZIS is a single-user, lifelong personal assistant: written now, voice later (P13), with personal memory later (P6+). It is not a chat app in which the user creates and manages conversations. The owner tested Phase 3 in the real app and decided:

- **The product:** one assistant identity, one continuous conversation, technical sessions in the background, and a central memory in the future.
- **Context limits are the system's problem.** The user should never see or handle them.

Constraints:

- Phase 3 already built a context engine that works **per conversation row**: window, summary, runtime token anchor, prefix hash, prompt cache and pre-warm. It is measured and tested.
- The owner's database may already hold several Phase 3 conversations used in parallel. Their messages may share timestamps.

## Options

| | A. One conversation record for everything | B. One timeline over several technical sessions |
|---|---|---|
| User experience | One timeline | One timeline (sessions hidden) |
| Existing parallel conversations | Must be merged into one: rewrites `conversation_id`/`seq` and summaries, and would interleave unrelated exchanges into one *model* context | Kept as closed sessions, unchanged; shown in one timeline |
| Context engine | Unchanged, but it inherits merged and confusing histories | Unchanged: it works on the active session |
| Future boundaries (memory era, model change, voice sessions) | None possible without new design | Possible without touching history |
| Complexity | Lowest code; riskiest migration | Small: a global order, one-active rule, timeline query |

## Decision: B, with the smallest possible mechanism

1. **Technical session = an existing `conversations` row.** There is no new table and no new abstraction.
2. **One active session.**
   - A partial unique index (`status = 'active'`) allows at most one.
   - Turns always go to it; it is created by the very first message.
   - The API takes no session id. The engine refuses turns for closed sessions (`session_not_active`).
3. **Session boundaries only on real technical need.** Phase 3 has none:
   - compaction keeps the active context bounded, so one session can continue indefinitely;
   - model changes are already handled inside a session (`context_version`).

   `start_new_session()` exists in the engine for future needs (memory era, P13 voice) and for tests and measurements. **Nothing calls it automatically.** There are no daily or arbitrary rollovers.

   A new session starts empty. The closed session's summary is **not** copied, because its citations (`refs`) point to the old session's message numbers and would be dropped or mis-verified. Continuity across sessions is the personal memory system's job (P6), with explicit source links.
4. **Unified timeline = a virtual view, not a merge.**
   - `messages.timeline_seq` is a global, unique, gap-free (at migration) display order.
   - New messages take `MAX + 1` inside the write transaction, which serializes writers.
   - Paging is keyset paging on that unique key, so no message is skipped or duplicated.
   - Each message keeps its `conversation_id` (= source session) and per-session `seq`.
5. **Visual timeline ≠ model context.**
   - The model sees only the active session (summary plus verbatim window), as in ADR-0010.
   - The UI marks the point where the active session starts: "Bu çizginin üstündeki mesajlar LAZIS'in güncel bağlamında değil". Older messages are therefore never presented as remembered.
   - S0 already instructs the model not to claim the user never said something it cannot see.
6. **Migration `0003_assistant_timeline`.** Forward-only and additive; one transaction, after the automatic encrypted pre-migration backup.
   - It adds `timeline_seq` and `channel`.
   - Existing messages are numbered **session by session** (sessions by last activity, then id; messages by their per-session `seq`). Earlier parallel conversations stay contiguous blocks instead of being interleaved by timestamp, and the most recently used session comes last.
   - The most recently used session stays `active`, the others become `archived`.
   - No row is deleted, merged or rewritten; summaries and context state are untouched. A second run is a no-op (`schema_migrations`).
7. **No history management over the API.** The routes to list, rename and delete conversations are removed. Deletion remains an engine function for a future, deliberate history-management feature, so no HTTP request can delete history.
8. **Input channel.** `messages.channel` is `text` now and `voice` from P13. It is one column with a default and no new table. The voice-specific fields planned in MEMORY_ARCHITECTURE (`interrupted`, `spoken_text`) arrive with P13.

## Consequences

**Performance.**
- Nothing in the prompt path changed: the active session's prefix, anchor and cache behave as before.
- Opening LAZIS pre-warms the **one** active session and nothing else.
- Timeline paging is an indexed range query; measured with 20,000 older messages in PHASE_3_REPORT §13.
- A session change is a new, small prefix: one cold prefill of the system prompt plus the new messages. The measured cost is in the report.

**Memory (P6+).**
- Memory records will cite `message_id` (globally unique, permanent) and may read the timeline across sessions.
- Memory does not depend on session ids.
- Retrieval will inject relevant facts into the active session's per-turn context note (ARCHITECTURE §6), which is how "dün konuştuğumuz projeye devam edelim" can work across session boundaries later.

**Voice (P13).**
- Spoken turns are messages with `channel = 'voice'` in the same timeline and the same active session; one identity, one history.
- A voice session (push-to-talk or hands-free) is a UI/audio concept, not a new technical session.

**Existing data.** The owner's Phase 3 conversations remain intact and readable in the timeline; only the most recent one continues as the active context.

**Not done** (no current need): history search and management UI, automatic session rollover, cross-session retrieval, list virtualization (paging covers the need).
