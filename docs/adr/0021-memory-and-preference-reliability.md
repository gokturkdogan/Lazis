# ADR-0021: Memory and preference reliability before adaptation (Phase 10A)

- **Status:** Implemented in Phase 10A (2026-10-31); awaiting the owner's approval with [PHASE_10_REPORT.md](../PHASE_10_REPORT.md). Phases 10B–10D not started.
- **Related:** [ADR-0017](0017-truthful-memory-claims.md) (claim guard), [ADR-0018](0018-namesakes-and-explicit-requests.md) (namesakes), [ADR-0020](0020-advanced-learning.md) (learning; open issues in PHASE_9_REPORT §22), [PERSONALITY_ENGINE.md](../PERSONALITY_ENGINE.md) §3–§4, [MEMORY_ARCHITECTURE.md](../MEMORY_ARCHITECTURE.md) Part P10A.

## Context

The owner accepted Phases 9 and 9.1 and kept three issues open (PHASE_9_REPORT §22). The owner then approved Phase 10 in four sub-phases. Phase 10A has to close those issues before anything adapts or speaks unasked:

1. **Certainty about an unsettled person.** Recall already holds back the facts of namesakes the message does not tell apart and asks the model to ask. The model still answered from the chat history: "Ahmet'in kardeşi Mehmet'tir. Ancak … hangi Ahmet?" (Phase 7 sessions 3.ask), and "Komşunuz olan Ahmet Bey'in emekli olduğunu anladım" (Phase 9.1 namesakes a2).
2. **A deleted fact from the chat history.** Forgetting deletes the records and keeps only keyed fingerprints. The words stay in the conversation and its summaries: "Mehmet bu kişilerden hangisinin kuzeniydi?" (Phase 7 6.ask). Proactive follow-ups and the relationship brief (Phase 10C) would read the same summaries.
3. **The same fact stored several times.** The same preference in other words becomes two or three records (Phase 9 r01). Phase 10B learns a preference from "≥ 3 signals in ≥ 2 sessions"; counting records would turn one statement into three signals.

Automatic preference learning may not be switched on before these safety tests pass (the owner's brief).

## Decision

1. **A people guard in the reply stream** (`conversation/people.py`): model → disclosure guard → people guard → claim guard. In a turn whose message leaves a namesake unsettled, it drops two kinds of sentence: one that states a candidate's stored fact without that candidate's label, and one that ties the user's news to some candidates' labels but not all. If the reply is then left without a question, it asks "Hangi Ahmet olduğunu belirtir misiniz?". The guard does not drop:
   - questions;
   - conditions ("… kastediyorsanız");
   - labeled answers ("Komşunuz Ahmet mimar");
   - lists of every candidate;
   - the user's own words.

   It also drops a sentence that speaks of a forgotten relationship or value. It works on whole sentences, and only in turns that have something to check. Released text is final, so shown = stored.
2. **Forgotten things are checked from fingerprints, never from text** (`memory/forgotten.py`). Forgetting now also writes a predicate-free value mark (an HMAC of the subject and the value) in the existing suppression table. An explicit save of the value clears it, and learning never reads it. A relation word counts for two other people only in the third person: the user's own "arkadaşınız" counts only for the user's relationships. A negated generic sentence ("aralarında kayıtlı bir ilişki bulunmuyor") does not count.
3. **One gate for what LAZIS raises unasked** (`memory/proactive.py`). Phase 10C's follow-ups and brief must read records and summaries through it. It refuses records that are:
   - forgotten or rejected;
   - not active;
   - in a pending conflict;
   - below 0.6 confidence;
   - sensitive;
   - inferred.

   Namesakes, and names with an open question, need a label. A summary sentence that speaks of something forgotten, or names such a person without a label, is dropped.
4. **Signals come from sources, not records** (`memory/signals.py`):
   - one per user message;
   - the same folded words count once;
   - sessions are counted separately;
   - only `message` evidence of the user's own messages counts (not imports, edits, confirmations or LAZIS's words);
   - only active records that were not forgotten or rejected count.

   The caller's key is the preference itself (Phase 10B: a style dimension and direction), never the record text.
5. **Found in the real runs and fixed in the same sub-phase:**
   - **Twins are forgotten together.** The user's employer and location are stored both as a fact and as a `works_at` / `lives_in` relationship. Forgetting the fact now also deletes and suppresses the twin relationship, and deletes an organization or place that nothing else refers to.
   - **Someone else's news is not the user's.** When the message names someone and the user's own words have no first person, a personal fact the model wrote about the user is dropped. Plans, events, decisions, goals and projects can be shared, so they are kept.
   - **A location with no place is a note.** A "location" with no residence word and no capitalized place ("emekli") is stored as a note.
   - **Summaries are cleaned line by line, and citations follow their sentence.** A dropped sentence takes its "[#n]" with it.

## Alternatives considered

- **Deleting or rewriting the forgotten words in the stored chat history.** This would change what the user sees in the timeline, and their history, for a reply-side problem. Rejected.
- **A stronger prompt only.** Recall's block already says "Cevap verme; önce hangisini kastettiğini sor" and the model still answered (3.ask). The guard enforces what the prompt asks.
- **Merging differently worded duplicates now.** That needs meaning, not word rules (Phase 9 §19-1). It is not needed for safety once signals are counted per message. The duplicates stay an open issue.
- **Holding every sentence in every turn.** That would delay the first text of every reply. The guard holds only in turns with an unsettled name, or with forgotten things when the user asks or names a stored person.

## Consequences

- In those turns the first text appears one sentence later: 0.2–1.4 s, and up to 2.2 s when a long sentence is dropped (PHASE_10_REPORT §8).
- Automatic preference learning stays off. `signals.py` and `proactive.py` are not called by anything yet; Phases 10B and 10C must read through them.
- The checks are word rules. An unknown phrasing can pass, and a sentence can be dropped that did not need to be. Each real run so far found new phrasings.
- Values forgotten before Phase 10A have no value mark, so text is not checked for them. Their relationship and record fingerprints still work.
- A sentence about a forgotten value that names neither the person nor the value ("Öğretmen olduğunu söylemiştiniz" about someone else) is not caught.
- Duplicate records stay (r01). They are not counted as independent signals.
