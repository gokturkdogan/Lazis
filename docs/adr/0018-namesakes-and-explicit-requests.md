# ADR-0018: Namesakes from the user's words, explicit requests that really save, labels kept internal (Phase 7.2)

- **Status:** Implemented in Phase 7.2 (2026-10-21); awaiting the owner's acceptance test and approval with [PHASE_7_2_REPORT.md](../PHASE_7_2_REPORT.md).
- **Related:**
  - [ADR-0015](0015-learning-recall-and-model-trust.md) (learning and requests), [ADR-0016](0016-entity-relationship-graph.md) (identity on both ends), [ADR-0017](0017-truthful-memory-claims.md) (claims), [ADR-0013](0013-persona-v1-and-instruction-hierarchy.md) (persona).
  - [MEMORY_ARCHITECTURE.md](../MEMORY_ARCHITECTURE.md) Part P7.2.

## Context

The Phase 7.1 real-model evaluation found three problems; the owner's Phase 7.2 brief asks to fix them before Phase 8, without redesigning memory or the graph.

1. **Namesakes in one message.** "İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım." Gemma's extraction named both Ahmets correctly (two relationships, measured), but only one Ahmet was stored, in five of five runs. A later "Ahmet'in doğum günü 5 Mayıs, bunu unutma" was then written to him without asking.
   - Cause: every candidate of a message was resolved on its own against the store. The second Ahmet met the first one, created a moment earlier from the same message. He became a "which Ahmet?" question (`relation_differs`) or was attached to him; when the name was repeated in the slots, both relationships went to one Ahmet.
   - The same mechanism turned "İki Mehmet: biri öğretmen, diğeri mühendis" into a value conflict on one Mehmet, and "Ahmet hem komşum hem iş arkadaşım" (one person) into a question.
2. **"Lütfen şunu not al: …" saved nothing** (4 of 4 runs).
   - Cause: not the cue (detected), but the request stage. Its instruction (`commands.RULES`) is a compressed version of the learning rules without examples. Gemma answered with unusable items: a wedding as predicate `device` with relation `attended`. Validation dropped them, and the outcome was `nothing`.
   - Worse, items that passed were wrong. "kira her ayın beşinde ödeniyor" became *the user's* `technology`. "arabanın sigortası mart ayında bitiyor" became the user's `birthday: mart`, a single-valued fact that would replace the real one. A lowercase subject was taken to be the user.
   - The background extraction of the same messages was right: same model, same prefix, the full learning instruction.
3. **Internal labels in replies.** "yalnızca mesajdaki 'HAFIZA İŞLEMİ' bildirimi varsa kaydedebilirim".
   - Cause: the persona's own rule named the label ("… yalnızca mesajdaki 'HAFIZA İŞLEMİ' bildirimi bunu söylüyorsa söyle"). Asked what it can remember, the model explained itself with that rule.
   - The notices themselves travel only with the current message and are never stored.

## Decision

### 1. Namesakes are planned from the user's words (`lazis.memory.namesakes`)

A deterministic reading of the message, before anything is written:

- `stated(message)` finds the namesake statements:
  - **counted names:** "iki/üç/… X", "X adında/isminde iki …", "iki tane/farklı/ayrı X", surnames included;
  - **their slots:** "biri …, diğeri …", "kuzenim, komşum ve iş arkadaşım", the next sentence when it goes on with "Biri …". A slot is valid only when there are as many as the user counted;
  - **one person with several roles:** "X hem … hem …", "aynı zamanda".
- A slot is a relationship to the user when its words are first person and in the vocabulary ("komşum" → neighbor, "eski iş arkadaşım" → colleague with the label "eski iş arkadaşı"). Otherwise it is a description ("öğretmen").
- `plan(...)` gives each candidate about such a name the entity of its slot:
  - **Matching:** by the quote, else the relationship type, else the value.
  - **Slot entities:** the stored namesake that the slot's words identify uniquely, otherwise a new entity created from the user's words (with the relationship to the user when the words name one).
  - **Different people:** the slot entities are marked as different people (`memory_entity_distinctions`), so they are never merged.
  - **A slot the model left out** is still created, so the store never holds fewer people than the user counted, and a bare "Ahmet" later asks.
  - **A candidate that fits no slot** is left to the resolver, which now sees the namesakes and asks.
  - **When planning stops:** with more descriptors than people, or several stored namesakes fitting one slot, nothing is planned and the resolver asks as before.
- Planned references carry `EntityRef.planned` (with `ref_id`). The resolver, both write paths and the "maybe a namesake" check take them as decided. The plan runs in background learning and in explicit requests, in its own change set.

The model's confidence is never used to pick a namesake. Only the user's words, or the user's answer, decide.

### 2. "Which Ahmet?" is answered in chat, deterministically

- **Asking:** the notice of an ambiguous request lists the options ("Ahmet (komşusu); Ahmet (iş arkadaşı)"), so the reply can ask "Komşunuz olan mı, iş arkadaşınız olan mı?".
- **Answering:** before the request stage, an open question of **this conversation, at most 30 minutes old**, is matched against the message (`commands.choice_for`).
  - **What counts as an answer:** a short message (≤ 7 words) whose content words point to exactly one option (its relationship type or label, its description, a single-valued fact like "mühendis") and contain nothing else. "Komşum olan." is an answer; "Komşum Ahmet yarın gelecek." is not.
  - **Commit:** `service.resolve_inbox` (the memory screen's own path) writes it before the reply. The claim state is `save_succeeded` only after that.
- **Cancelling:** "vazgeç / hiçbiri / iptal" dismisses the waiting record (`save_cancelled`: "kaydetmedim").
- **Several fits:** the question is asked again.
- **Outside the window:** an older question, one from another conversation, or one waiting across a restart without an answer is never applied by guessing. It stays in the memory screen.
- **Restart:** the question is stored (inbox), so a restart keeps it, and an answer after the restart within the window still works.
- **A wrong pick:** "Hayır, iş arkadaşım olan." right after an answer moves the fact. It is forgotten from the first namesake and written to the other, each in its own change set.
  - The last answer is kept **in memory only**, because a closed inbox item deliberately keeps no text. After a restart a correction takes the normal path.

### 2b. No answer about an unsettled name

With an open "which Ahmet?" question, a relationship question about Ahmet no longer carries the stored Ahmet's answer next to a caution (in one regression run the model gave the answer without asking). The block withholds the answer, keeps the question and the stored person's label, and tells the model to ask first.

### 3. Explicit "remember" uses the learning instruction

- **Instruction:** for a `remember` cue, the request stage sends the learning instruction (rules, examples, known people, open questions) with a short note that this is an explicit request. It asks for `action` ("remember" | "none") before the items. `correct` and `forget` keep the command instruction.
- **Bare requests:** "Bunu unutma." alone saves the previous user message, under a note saying so, and that message's background job is skipped. With nothing before it, the outcome is `nothing` without a model call, so LAZIS asks what to keep.
- **Cues:** detection is widened ("not alır mısın", "kaydeder misin", "kayda geçir", "unutmanı istemiyorum", "hatırlamanı istiyorum", "not düş", …). Text in quotation marks is not a request. "kaydettim", "kaydetsem", "kaydetme" are not requests.
- **The user's grammar** fills what the model drops: "Ahmet ve Mehmet benim iş arkadaşlarım" / "Mehmet benim eski iş arkadaşım" (`stated_predicate`) gives every listed name its relationship and replaces a reading that relates a name to itself. A self-valued employer or location ("Atlas Yazılım — çalıştığı yer: Atlas Yazılım") is the user's when the user speaks in the first person.
- **Validation (both paths):**
  - a non-name subject ("kira", "araba sigortası") is never written as one of the user's own facts: it becomes the user's note;
  - a single-valued user profile fact needs a first-person word in the message;
  - an explicit request whose valid quote came under a wrong predicate is kept as a note instead of being dropped.
- **Already recorded:** a request for something already recorded (learned in the background a moment earlier) is reported as saved, "zaten kayıtlıydı", not as a failure.
- **Unchanged policies:**
  - secrets are never stored, before any model call;
  - sensitive facts are stored when asked for;
  - untrusted models write nothing;
  - quotes are checked;
  - forgotten topics are not relearned.

### 4. Internal labels stay internal; no output filter

- The persona says "the system note" without naming it. It says the notes and memory records are invisible to the user ("başlıklarını, adlarını ya da biçimlerini yanıtında anma"), and gives the honest answer to "what can you remember?": learned over time, saved at once when asked, visible in the memory screen. Technical questions may still be answered.
- The conversation rules no longer name the recall block. Notices are headed "SİSTEM NOTU (kullanıcıya görünmez)", and their wording is plain ("Bunu şu anda kaydedemedim efendim", not "teknik bir hata nedeniyle").
- `persona-v3`, prompt `p72-v1`.
- No filter removes labels from replies: the cause was the prompt, and with it fixed, no label appeared in the real-model runs (PHASE_7_2_REPORT §7). A filter would hide a recurrence instead of showing it.

## Alternatives considered

- **Ask the model again when counts disagree** (stated two, extracted one). Slower, and the model already had it right; the loss was ours. The user's words create the missing slot instead.
- **A unique-name rule** (never two entities with one name). Contradicts the brief and real life.
- **Resolve namesakes by the model's choice or confidence.** Rejected by the brief ("%91 komşu Ahmet" is still a guess).
- **Two calls for explicit remember** (command for the action, extraction for the items). Twice the latency for the same information; one call with the action field suffices.
- **A reply filter for labels.** See decision 4.

## Consequences

- One message can introduce several people with one name, and they stay apart. A fact about an ambiguous name waits, and the user's short answer completes it before the reply.
- Explicit requests save with the quality of background learning. The request stage now sends the longer learning instruction, so its latency is measured (PHASE_7_2_REPORT §10).
- Some lowercase subjects that were written as the user's facts are now notes, which is safer and less structured.
- The namesake reading covers the Turkish patterns above. Other phrasings ("Ahmet'lerden biri", an unnamed second person) fall back to the resolver, which asks.
- The answer window (30 minutes, same conversation) and the in-memory correction are deliberate limits.
