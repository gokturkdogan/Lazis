# ADR-0020: Advanced automatic learning — whole lists, the right time, the right person (Phase 9)

- **Status:** Implemented in Phase 9 (2026-10-28); awaiting the owner's acceptance test and approval with [PHASE_9_REPORT.md](../PHASE_9_REPORT.md).
- **Related:** [ADR-0014](0014-personal-memory-store.md) (store, consolidation), [ADR-0015](0015-learning-recall-and-model-trust.md) (learning), [ADR-0016](0016-entity-relationship-graph.md) (graph), [ADR-0017](0017-truthful-memory-claims.md) (claims), [ADR-0018](0018-namesakes-and-explicit-requests.md) (namesakes), [ADR-0019](0019-personal-knowledge-bootstrap.md) (import), [MEMORY_ARCHITECTURE.md](../MEMORY_ARCHITECTURE.md) Part P9.

## Context

Before changing anything, the brief's sentences were run through background learning with the real model (Gemma 4 12B), on throwaway profiles, and the database was read:

| Message | What was stored |
|---|---|
| "Ahmet'in iki kardeşi var: Mehmet ve Ali." (and two other wordings) | only Mehmet |
| "Annemin üç kardeşi var: Ayşe, Fatma ve Zeynep." | three **siblings of the user** |
| "Geçen yıl Kervan'da çalışıyordum, artık Pusula'dayım." | Kervan current, Pusula history — **reversed** |
| "Gelecek yıl İzmir'e taşınacağım." | current city İzmir |
| "İstanbul, Ankara ve İzmir'de yaşadım." | current city İstanbul |
| "Mehmet Ankara'da yaşıyor." → "Mehmet İstanbul'da yaşıyor." | Ankara silently replaced |
| "… sabah çalışmayı seviyorum" in three wordings | three records |
| "Hayır, Ahmet değil Mehmet demek istedim." | both had the birthday |
| "Annemin üç kardeşi …" (another run) | the job failed three times: the model's JSON broke near its end; the message was never learned from |

The extraction prompt and validation were tuned on the Phase 6/7 gold sets; the problems are in what the model does with lists and tense, and in what happens between validation and the write.

## Decision

### 1. A refinement step between validation and the write, from the user's own words (`memory.refine`, `memory.temporal`)

Both learning and explicit requests pass validated items through it. It never adds a fact or a relationship; it decides *when* and *whose*:

- **Tense** of the clause the quote is in (clauses end at a full stop or at a comma / "ama" turning to another time — not inside a list; a quote that spans clauses is read in the clause with its value or person): *past* ("eskiden", "önceden", "geçen yıl … -yordum", "-mıştım", "yaşadım/çalıştım/okudum") → **history**; *future* ("-acağım", "gelecek yıl", "seneye", "yakında") → a **plan**; *current* otherwise, including a change that happened ("taşındım", "geçen ay başlattım").
- History is written as a superseded record that never replaces today's value (the same value already current ends now; the same value already history only gets evidence). No end date is invented.
- Relationships: past → `ended`, future → `planned`; a model's `ended` for "artık X'teyim" (present, not negated) → `active`.
- **Change**: the model's "it changed" counts only when the words say so ("artık", "taşındı", "… beri", "aslında" …). Otherwise a different single value is a conflict (the inbox asks).
- **Time named**: the user's phrase ("2024'te", "geçen ay", "Üç yıl önce") is kept as written, never turned into a date.
- **Someone else's relatives**: "annemin/babamın kardeşleri" → `parent_sibling`; any other "-(ı)mın X'i" ("arkadaşımın kardeşi") is not the user's relationship → dropped.
- **Passing states**: "bugün / şu an / bu akşam" with a preference or note and no word of lasting ("hiç", "her zaman", "genelde") → not kept.

### 2. Whole lists without inventing anyone (`memory.lists`)

Lists are found in the user's words (names or short values joined by commas and "ve/ile/veya"; a count before them). If the model extracted something about some members and nothing about others, the learning job asks the model once more — a focused instruction naming the list, what was found and what is missing — and keeps only answers about the missing members (validated as usual). At most two such reads per job. A count that differs from the names given ("üç kardeşi var: Mehmet ve Ali") is kept as the user's own words in a note on that person; nobody is invented.

Rejected alternative: expanding a relationship to every coordinated name by rule. It invents relationships when the list is the object of something else ("Ahmet'in kardeşi Mehmet ve Ali'yle tanıştım").

### 3. Broken answers are salvaged, not lost

When the model's JSON breaks near its end (seen with Gemma), the complete objects before the break are kept (`extraction.salvage`) and validated as usual; a list re-read can still recover the dropped one. Artefacts the model appends to sentences ("….causal_link_id_1") are stripped.

### 4. Repetition is evidence, never truth

- The same message (or import item) read again is not a second piece of evidence (`add_evidence` returns False).
- Each other message adds a source; confidence rises by 0.03 per source up to 0.95 — never to certainty.
- Repetition never settles a conflict or outweighs a correction: those go through their own paths.
- The model is shown stored preferences and habits that share a word stem with the message and told to reuse the stored value when the user says the same thing in other words (rule 15).

### 5. Importance is computed, never a reason to write (`memory.importance`)

Five tiers (`critical_personal`, `high`, `medium`, `low`, `ephemeral`) from predicate, subject, sensitivity, origin and independent sources. They order recall ties, quality suggestions and the memory screen's badges. Nothing is written because of a tier; ephemeral states are dropped by the refinement step.

### 6. Corrections in so many words (`memory.corrections`)

"Hayır / Yok / Pardon / Aslında …, X değil Y (demek istedim)" is handled before the reply, without a model call, on what the last user message taught:

- X a person → those records move to Y (the stored Y, or a new person; a person that existed only because of that message is renamed);
- X a value, or a workplace or place → the value (and that entity) is corrected;
- Y could be several people, or another Y is still waiting for "which one?" → the user is asked;
- the message was not learned from yet → the correction waits for it (in memory; lost on restart);
- one change set; history keeps what it was.

"Hayır, vazgeç" now calls off a waiting "which one?" like "Vazgeç".

### 7. Quality checks are suggestions (`memory.quality`, migration `0007_quality`)

A read-only scan, in priority order (tier, then kind): two current values of one fact, waiting conflicts, near duplicates, a changing fact not confirmed for a year, two people with one name neither told apart nor merged, facts without any source, uncertain or inferred facts. The user edits, forgets, merges or hides the suggestion. A hidden suggestion is remembered by a content-free fingerprint (the only new table). Nothing is rewritten, merged or deleted by the scan.

## Consequences

- One more model call per learning job only when a list was partly read (measured in the report).
- History values appear in the memory screen as "geçmişte"; recall already treated superseded values as history.
- The extraction instruction changed (rules 14–15, two examples with names absent from the gold sets); the Phase 6/7 gold sets were re-run.
- Not handled: a correction waiting for an unlearned message does not survive a restart; tense is read from words, not grammar, and can miss unusual forms (reported, with the cases, in PHASE_9_REPORT §17).
