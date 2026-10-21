# ADR-0017: Truthful memory claims — a deterministic streaming guard keyed on the real outcome (Phase 7.1)

- **Status:** Implemented in Phase 7.1 (2026-10-21); awaiting the owner's acceptance test and approval with [PHASE_7_1_REPORT.md](../PHASE_7_1_REPORT.md).
- **Related:** [ADR-0015](0015-learning-recall-and-model-trust.md) (requests in chat, the notices), [ADR-0016](0016-entity-relationship-graph.md), [MEMORY_ARCHITECTURE.md](../MEMORY_ARCHITECTURE.md) Part P7.1, [PHASE_7_REPORT.md §M-2](../PHASE_7_REPORT.md).

## Context

A statement ("Ahmet'in kardeşi Mehmet.") is learned in the background after the reply (ADR-0015): the learning queue runs once the turn is idle. Yet the reply often said "not aldım", "hafızama kaydettim" or "bunu unutmayacağım" — before anything was written. The model is told this in the turn notice ("Bu mesajdaki bilgiler henüz hafızaya yazılmadı … kaydetmekten söz etme"). Measured in the Phase 7 sessions, it still claimed a save in 5 of 9 statement replies; a reworded notice cut a 10-statement A/B from 3/10 to 1/10, but not the full sessions. A claim that may be false is worse than no claim: the owner relies on what LAZIS says it has stored.

The owner's Phase 7.1 brief asks for an application-level guarantee:

- the claim follows the **real** memory operation, never the model's own words;
- no false claim is visible at any point of the stream, including when a claim is split across chunks;
- the shown, stored and (later) spoken text are identical;
- no second model call;
- no change to learning, the graph, the queue, or the schema;
- no added waiting.

## Decision

### 1. The state comes from the operation

`lazis.memory.claims.state_for(intent, outcome, statement, learning)` maps the turn's explicit request (`commands.detect`) and its executed outcome (`commands.Outcome.kind`, known before the reply starts — requests already run before the reply, ADR-0015) to a `ClaimState`:

| State | When |
|---|---|
| `save_succeeded` / `update_succeeded` / `delete_succeeded` | the request committed (`saved`; `corrected`/`merged`/`distinguished`; `forgotten`) |
| `save_pending` / `delete_pending` | the request waits for the user (`confirm_needed`, `ambiguous`) |
| `save_failed` / `update_failed` / `delete_failed` | any other outcome (failed, refused, not found, untrusted model, secret) |
| `auto_learning_pending` | no request; the message is a statement and background learning will process it |
| `no_memory_action` | everything else |

A `Policy` adds two facts of the turn: whether recall brought stored memory (`has_memory`; references to existing records need it) and whether the turn is a memory request (delete/update verbs count as memory acts then).

### 2. A deterministic Turkish classifier, one sentence at a time

On folded text (Turkish lower-casing, diacritics removed, length preserved so offsets map back), a sentence is a **claim** when it carries a completed or committed memory act by LAZIS: first person past, present, future or the passive completion of a save verb ("kaydettim", "not aldım", "kayda geçirdim", "hafızama ekledim", "kaydedildi"), a commitment ("unutmayacağım", "aklımda tutacağım", "artık hatırlayacağım"), "öğrendim", note and record nouns with possessive or accusative endings ("notunuzu aldım", "Ahmet'in kaydını aldım", "bir kayıt oluşturdum", "kayda aldım"; added after the first real-model run, PHASE_7_1_REPORT §6), a save verb after a first person storage noun in the dative, adjacent or later in the sentence ("bilgilerime / listeme ekledim", "Not defterime X'i ekledim"; also found with the real model), or a delete/update verb next to a memory word or in a memory request. It is **not** a claim when negated or unable ("kaydetmedim", "kaydedemedim"), an offer or ability ("kaydedebilirim", "kaydedeyim mi"), a question, another person's act ("kaydettiniz", "Ahmet not etmiş"), inside quotation marks, only talked about ("not aldım gibi", "kaydettim diye"), or a statement that nothing is stored. A **reference to an existing record** ("daha önce kaydettiğimiz", "hafızamdaki bilgiye göre", "kaydedilmiş") is allowed only with `has_memory`; without it, it is pointed at the conversation ("konuştuğumuz", "konuşmamızdaki").

Rules rather than a model: the guard must be predictable, testable phrase by phrase, cost nothing, and never be argued out of its job by the text it is checking.

### 3. Minimal rewording

Only the claim is reworded; the rest of the sentence and the reply is kept:

- pending learning: the verb becomes "anladım" ("Mehmet olduğunu not ettim" → "Mehmet olduğunu anladım"); a sentence that already acknowledged ("Anladım ve not aldım.") drops the redundant clause instead;
- failure: "kaydedemedim", "silmedim", "güncelleyemedim";
- pending: "henüz kaydetmedim", "henüz silmedim";
- passive forms take the passive ("anlaşıldı", "kaydedilemedi");
- a note/record noun object becomes "bilgisini / bilgiyi / bilgilerini", so the sentence keeps its grammar ("Toplantının notunu aldım" → "Toplantının bilgisini anladım").

Nothing is added: no explanation, no technical text, no save is started.

### 4. Streaming: hold back only what could become a claim

`ClaimGuard` sits between the model stream and every consumer (UI deltas, partial flushes, the final message, cancellation). Text is released as it arrives, with a lag of one word (two when the last word is the beginning of a risky stem, so "n" + "ot aldım" cannot leak the connector before it). From the first word that could begin a claim (a save, memory, commitment stem; delete/update stems only in a memory context) the guard holds the rest of the sentence until it ends, then classifies and rewrites it. A held span longer than 240 characters is released after classification at that point (a runaway sentence must not freeze the reply). Released text is never taken back, so a rewrite only touches text the user has not seen; when the already-shown part makes a deletion ungrammatical, the claim is reworded instead of dropped.

The engine stores and returns `guard.released`: the done message, the partial flushes, and the cancelled or failed reply are exactly what the user saw.

### 5. The model notice stays

The Phase 6/7 notices (the positive "nothing written yet" wording) remain: they keep claims rarer, so the guard rewrites less. The guard is the guarantee; the notice is the first line.

### 6. Diagnostics, no content

The last-turn diagnostics gain `claim_state`, `claims_rewritten` and `first_shown_ms` (when the user saw the first text, vs `ttft_ms` from the model). The log event `memory.claims_rewritten` carries the state, count and kinds — never the text.

## Alternatives considered

- **(a) Better prompting only.** Tried in Phase 7 (two notice wordings); the claim rate in full sessions stayed at 5/9. Not a guarantee.
- **(b) Learn synchronously before the reply.** Makes every statement wait 5–8 s for extraction (ADR-0015 moved this to the background for that reason); the brief forbids it.
- **(c) A second model call to check or rewrite the reply.** Adds latency, can itself be wrong, and the brief forbids it.
- **(d) Buffer the whole reply.** Simple and safe, but the first text would appear only when the model finishes (seconds); the brief requires fluent streaming.
- **(e) Strip claim sentences instead of rewording.** Loses content the user said ("Ahmet'in kardeşi Mehmet olduğunu not ettim" carries the restatement).

## Consequences

- The reply can no longer claim a memory operation that did not happen in the turn, in any chunking; the guard's rules are covered by ≥100 phrase tests, exhaustive two-part and random chunkings, and engine tests.
- Phrasing outside the rules (a new idiom for "saved") is not caught; such a miss is a false claim the notice should still prevent, and the evaluation word list is wider than the guard's to surface it. Adding a rule is a one-line change with a test.
- Sentences containing a risky stem stream a sentence at a time instead of a word at a time; measured cost in PHASE_7_1_REPORT §8.
- References to a past record are only allowed when recall brought memory in this turn; "daha önce kaydettiğimiz" about something not recalled is pointed at the conversation instead.
- The voice pipeline (later phase) must read the guarded text, not the model stream.
