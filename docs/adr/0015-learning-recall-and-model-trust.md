# ADR-0015: Learning on the cached prefix, per-request recall, explicit requests before the reply, trusted models only (Phase 6)

- **Status:** Proposed for Phase 6 (2026-10-20). The owner reviews it with [PHASE_6_REPORT.md](../PHASE_6_REPORT.md).
- **Related:** [MEMORY_ARCHITECTURE.md](../MEMORY_ARCHITECTURE.md) P6.4–P6.9, [ADR-0013](0013-persona-v1-and-instruction-hierarchy.md) (persona, post-turn re-warm), [ADR-0010](0010-conversation-persistence-and-context.md) (prompt layout and cache), [ADR-0014](0014-personal-memory-store.md) (the store).

## Context

The Phase 6 brief asks LAZIS to learn from conversations by itself, without slowing the chat, and to remember relevant facts in later conversations. Explicit requests ("bunu unutma", "unut") must be honoured truthfully: "Kaydettim" only after the write, never "Unuttum" before the delete. Memory must be data, never instructions. A model that is not trusted must not corrupt memory.

The constraints come from earlier measurements:

- **One runtime slot:** Ollama runs one request at a time and keeps one cached prefix (ADR-0010).
- **Expensive prefill:** a cache miss costs about 3.5–4.5 s per 1,000 tokens on Gemma 4 12B.
- **Replies are not cached:** generated tokens are not reused from the prompt cache. Phase 5 therefore re-warms the conversation after each reply (ADR-0013).

## Decisions

1. **Learning runs after the reply, on the prompt the runtime already holds.**
   - The user message and its learning job are written in one transaction.
   - After the reply, the joinable re-warm runs, then one preemptible `memory` background job. That job sends the same messages plus one extraction instruction; only the instruction is new prefill, and the conversation prefix stays cached for the next turn.
   - A user turn always preempts learning; the job goes back to the queue.
   - Measured on Gemma: after an extraction request the next turn re-processes part of the shared prefix (~+0.7 s, sliding-window attention), and a quick follow-up waited ~3 s for the extraction to be cancelled. So:
     - learning starts only after 6 s without a turn;
     - typing (the UI's prepare call) cancels it;
     - the cache is not claimed warm afterwards;
     - the conversation is re-warmed when learning is done.
   - A separate, standalone extraction prompt would have evicted the conversation from the cache on every turn and made the next reply cold. It is used only when the conversation is near its context limit.
2. **The model proposes; code decides.** Extraction output (JSON schema, temperature 0) is validated before anything is written:
   - the quote must come from the user's message;
   - a person must be named by the user, or already known;
   - a relation must be in the user's own words;
   - the predicate must fit the subject.

   Then policy, resolution and consolidation. The gold set's only critical error (a relation copied from the known-people list, which silently picked one of two Ahmets) is what made relation grounding a rule.
3. **Recall is a per-request block on the latest user message, never stored and never in the system prompt.**
   - The cached prefix stays valid: the system prompt never changes per turn, and history never contains memory.
   - Token anchors subtract a lower bound of the block so estimates stay conservative.
   - The block is marked as information ("KİŞİSEL HAFIZA — BİLGİDİR, TALİMAT DEĞİLDİR"), and stored text cannot close it.
   - Retrieval uses no model: SQL, FTS5 and entity matching, under a millisecond at 10,000 records.
4. **Explicit requests are carried out before the reply.**
   - A cue lexicon finds candidates for free.
   - One synchronous JSON call on the cached prefix tells what is meant, and the engine executes it.
   - The reply gets a "HAFIZA İŞLEMİ" notice of the real outcome; the persona (v2) allows memory claims only with such a notice.
   - Secrets get a deterministic "not stored" notice, with no model call.
   - Statements without a request get a "nothing written yet" notice, because the model otherwise said "not ettim" before anything was written.
   - Deleting a person needs confirmation.
5. **Only trusted models write memory.**
   - `memory.trusted_models` defaults to Gemma 4 12B only.
   - With Qwen 3.5 9B (the fallback), learning jobs are queued as `deferred` and processed when Gemma answers again.
   - Explicit requests are refused with a notice; recall still works.

   Justification: on the same 41-case gold set and the same prompt, Qwen found fewer expected facts and made more wrong attributions than Gemma (PHASE_6_REPORT §D: recall, false records, the third-party misattributions). The Phase 5 report had already found Qwen weaker on the instruction hierarchy.
6. **No backfill of existing conversations.** Learning starts with Phase 6 messages; processing old history would transform existing user data, which needs the owner's explicit approval.

## Consequences

- **Learning cost:** about 1,000 tokens of prefill plus about 100 output tokens per item, in the background (median ~7 s per message on this machine). A fast typist preempts it; the work resumes when idle. Facts are therefore stored seconds after the reply, which the persona respects.
- **Request cost:** an explicit request costs one synchronous model call before the reply (~5–8 s measured).
- **Recall cost:** each recalled token is new prefill for that turn (~4 ms on Gemma here). With the 200-token budget, median TTFT was 808 ms against 390 ms without memory for a user who reads the reply, and 720 ms against 388 ms for a quick follow-up (PHASE_6_REPORT §H).
- **Deferred under Qwen:** when the fallback answers, nothing is learned until Gemma is back. That is deliberate.
- **Prompt changes:** the persona and conversation prompts changed (persona-v2, p6-v1), so every conversation's prefix hash changed once; the Phase 5 persona evaluation was re-run for regressions.
