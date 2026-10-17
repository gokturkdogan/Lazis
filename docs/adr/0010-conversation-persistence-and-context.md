# ADR-0010: Conversation persistence and context management

- **Status:** Accepted for Phase 3 (2026-10-17). **Superseded in part by [ADR-0011](0011-single-assistant-timeline.md)** (2026-10-18): the user no longer creates, lists, renames or deletes conversations; a `conversations` row is now a hidden technical session, and the user sees one timeline. Storage, turn lifecycle, prompt layout, budget, compaction, scheduler and pre-warm below are unchanged.
- **Related:**
  - [ARCHITECTURE.md §6](../ARCHITECTURE.md) (prompt assembly) and [§8.1](../ARCHITECTURE.md) (API)
  - [MEMORY_ARCHITECTURE.md §5, §17](../MEMORY_ARCHITECTURE.md)
  - [ADR-0001](0001-primary-model.md) (model, G2-r1)
  - [ADR-0003](0003-storage-driver-and-encryption.md), [ADR-0009](0009-backend-network-sandbox.md)
  - [PHASE_3_REPORT.md](../PHASE_3_REPORT.md)

## Context

Phase 3 turns the ephemeral Phase 2 preview into persistent, multi-turn conversations, which raises four needs:

- **Security:** keep the security model unchanged (SQLCipher, Keychain, loopback API, port-restricted sandbox).
- **Latency:** survive long histories on a 24 GB Mac. Phase 2 measured Gemma 4 12B cache misses at 8.1 s at 2.2K tokens and 50.3 s at 11.9K.
- **Honest summaries:** keep summaries from inventing or misattributing facts.
- **Separation from memory:** keep chat history apart from the personal memory that comes in Phase 6.

## Decisions

### 1. Storage (`0002_conversations`)

- **Tables:**
  - `conversations`;
  - `messages`: per-conversation `seq` assigned inside the write transaction, a unique client idempotency key (`client_id`), and a `status` that is one of `complete`, `streaming`, `cancelled`, `interrupted` or `failed`;
  - `context_summaries`: regenerable, and each covers `[from_seq, to_seq]`; every item cites message numbers;
  - `conversation_context`: the verbatim window start, the active summary, the runtime token anchor and the prefix hash.
- **Deletion:** `ON DELETE CASCADE` removes messages, context state and summaries with their conversation.
- **Not tracked by change sets.** Conversation rows do not go through the change-set/`history` mechanism (ARCHITECTURE §4, rule 7). That mechanism copies before/after row images into `history`, which would put a second copy of every message where deleting the conversation could not remove it. Rule 7 governs knowledge writes (memories, entities). Chat history is not knowledge; it is the raw source that later phases may cite.
- **Deletion audit:** written to `audit_log` with the conversation id and counts only.
- **Segments:** the `segments` table planned for `0002` in MEMORY_ARCHITECTURE §5.2 is not created. It belongs to the learning pipeline (P9) and arrives with its first consumer.

### 2. Turn lifecycle

1. In one transaction, the user message and an empty `streaming` reply row are stored. A repeated `client_id` is refused with `turn_duplicate`.
2. Busy runtime, unknown conversation, missing model, unavailable runtime and an oversized message are refused before anything is stored.
3. The reply is streamed. Partial text is persisted at most every 1 s or 400 characters.
4. The row is closed exactly once: `complete`, `cancelled` (user or client disconnect), `interrupted` (backend shutdown) or `failed` (runtime error, with `error_code`).
5. On startup, any row still `streaming` (crash) becomes `interrupted`.

### 3. What later prompts contain

| Reply status | Included in later prompts |
|---|---|
| `complete` | Verbatim |
| `cancelled` (non-empty) | With the marker `[Bu yanıt kullanıcı tarafından yarıda kesildi.]` — the user saw that text |
| `interrupted` (non-empty) | With the marker `[Bu yanıt uygulama kapandığı için yarım kaldı.]` |
| `failed` | Never |
| `streaming` | Never |
| Empty | Never |

### 4. Prompt layout (ARCHITECTURE §6)

- **System message:**
  - `S0` safety, privacy and context-honesty rules;
  - `S1` persona v0;
  - `S2` tools: none;
  - `S3` profile: none before Phase 6;
  - the conversation summary;
  - when messages had to be left out, a note naming the omitted range.
- **History and new message:** the verbatim history, then the new user message.
- **Time notes:** each user message carries a time note (`[Mesaj zamanı: …]`). It is rendered once when the message is sent and stored with the message, so later prompts are byte-identical.
- **Stable prefix:** the prefix hash covers the prompt version, model, `num_ctx` and system text. Within a `context_version` the history is append-only.

### 5. Token budget

- **No tokenizer endpoint.** Ollama 0.40.4 has no tokenize endpoint (checked), so budgets are anchored on the runtime's own counts.
  - After each turn, `anchor_tokens` = `prompt_eval_count`.
  - The next estimate adds only what came after the anchor: the reply's `eval_count` plus template tokens, and the new message.
- **Estimating text the runtime has not counted.** Such text is estimated conservatively at 2.2 characters per token (measured Turkish: 2.5–3.8).
- **Limits:**
  - **Hard limit:** `num_ctx` − reply reserve (`max_output_tokens`) − 10 % margin, i.e. 13,721 of 16,384 tokens.
  - **Idle compaction:** starts above 6,144 tokens. This is chosen from the cold-cache cost of about 3.5–4.5 s per 1K tokens.

### 6. Compaction

- **When:**
  - In the background, when the user is idle (default 5 s after a turn, so it runs while the user reads the reply), the engine compacts. A turn preempts it.
  - Synchronously, before a turn that would exceed the hard limit, with a visible `compacting` stage.
- **What is kept verbatim:** the last ≥ 4 messages or about 2,048 tokens, starting at a user turn. The rest is folded into the summary in chunks of about 6,000 estimated tokens. Each chunk ends before a user message and **its summary is persisted before the next chunk starts**, so a preempted or failed compaction keeps the progress made so far.
- **Summary format:** schema-constrained JSON. Sections: goals, topics, decisions (with `current`), open questions, constraints, people, instructions, assistant notes. Each item has `source` (user or assistant), `refs`, a verbatim `quote` and `certain`.
- **Evidence check in code:** each item must pass against the original stored messages, or it is dropped and counted:
  - the cited messages must exist inside the summarized range;
  - a user item must cite a user message, and its quote must occur in one of them (normalized, fuzzy ≥ 0.85);
  - a LAZIS item must cite an assistant message.
- **Rendering:**
  - LAZIS's suggestions are rendered apart from what the user said;
  - replaced decisions are marked "artık geçerli değil";
  - uncertain items are marked "(belirsiz)".
- **Robustness:**
  - Output cut off at the token limit is salvaged item by item.
  - Instructions ask for single-line JSON without duplicated items. This halved the output tokens (measured 1,070 → 520 for one dialogue).
- **Original messages:** they are never altered. `reset_context` invalidates all summaries; the next compaction rebuilds them.
- **Fallback.** If compaction is impossible (runtime error, invalid output) and the prompt is over the hard limit, the oldest verbatim messages are left out:
  - the persisted state becomes `window_only`, so the prefix stays stable;
  - the model is told which range is missing and to say it does not remember it;
  - the UI shows the range.
  - Nothing is cut silently.

### 7. Runtime slot and cache warming

- **One scheduler.** It owns the single runtime slot for every LAZIS request, including the Phase 2 preview chat.
  - A turn preempts background work (compaction or pre-warm), except a pre-warm of exactly its own conversation: the turn waits for that one, since the prefill is not wasted.
  - Every request first clears the scheduler's "what is cached" record; only a completed request sets it.
- **Pre-warming.** A one-token request on the stored prompt fills the runtime's cache. It runs:
  - when a conversation is opened;
  - when the window becomes visible again;
  - on composer input, at most every 30 s;
  - after compaction.

  Measured before implementation: on a 2.6K-token history, the TTFT was 0.24 s after a pre-warm against 8.5 s cold.
- **Keep-alive** stays at 10 minutes. Keeping the 7.4 GB model resident longer was rejected: Phase 2 measured swap growth with typical apps open. Pre-warming on focus and open covers reloads instead. The report gives the reload cost.

### 7a. llama.cpp's host-RAM prompt cache (found during the Phase 3 measurements)

- **What it is.** The llama.cpp server inside Ollama 0.40.4 saves earlier prompt states into host RAM and restores the most similar one on a later request (`--cache-ram`). Ollama does not set this option, so llama.cpp's default of 8,192 MiB applied.
- **Effect.** A conversation pushed out of the runtime slot by another request comes back in 0.9–1.4 s instead of being prefilled again.
- **Cost.** With the default, the runner's footprint reached 13.2 GB during the benchmark on this 24 GB Mac, with the cache full at 8,159 MiB and 31 prompts. That comes on top of the model.
- **Decision:** `scripts/ollama-agent.sh` sets `LLAMA_ARG_CACHE_RAM=2048` (override: `LAZIS_PROMPT_CACHE_MIB`). Measured with the cap:
  - runner peak 6.4 GB instead of 13.2 GB;
  - an immediate restore is still about 1 s;
  - returning to an 8K conversation after other activity can need a full prefill (32.6 s in the benchmark) unless it is pre-warmed. With pre-warm: 0.40 s.
  - The memory saving outweighs this; pre-warm on open covers the common case.

### 8. Deletion

- **The live database:**
  - one transaction removes all rows and writes the audit row;
  - then `PRAGMA wal_checkpoint(TRUNCATE)`;
  - `secure_delete=ON` was already set and zeroes freed pages.
- **The runtime:** if its prompt cache held the deleted conversation, the model is unloaded.
- **Backups:** older encrypted backups still contain the conversation until they rotate. The confirmation dialog says this, and also that physical erasure on the SSD cannot be guaranteed.

### 9. Transport

- Turns stream as NDJSON over the existing authenticated HTTP API: `start` → `status`… → `delta`… → `done` | `cancelled` | `error`.
- The roadmap's WebSocket hub is **not** added. The backend refuses WebSocket upgrades (Phase 1.1), and adding WebSocket would widen the API surface for no Phase 3 need.

## Consequences

- Chats survive restarts and crashes without showing an unfinished reply as finished.
- Context cost stays bounded. Cache misses after switching, restarting or a model reload are hidden by pre-warming when the user takes longer to type than the prefill takes. Measured results are in PHASE_3_REPORT §7.
- Summaries can lose detail; that is the price of a bounded context. The originals stay available, and evidence-checked items cannot attribute LAZIS's words to the user or carry quotes that are not in the messages.
- **Phase 6 boundary:** later phases may read messages only through cited interfaces (`message_id`, `seq`). No facts are extracted in Phase 3.
