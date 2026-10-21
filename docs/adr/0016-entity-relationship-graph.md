# ADR-0016: Entity and relationship graph — typed edges on the Phase 6 store, deterministic paths (Phase 7)

- **Status:** Implemented in Phase 7 (2026-10-20); awaiting the owner's acceptance test and approval with [PHASE_7_REPORT.md](../PHASE_7_REPORT.md).
- **Related:**
  - [KNOWLEDGE_GRAPH_DESIGN.md](../KNOWLEDGE_GRAPH_DESIGN.md): the Phase 0 design. This ADR records what Phase 7 builds from it and what it defers.
  - [ADR-0014](0014-personal-memory-store.md) (store), [ADR-0015](0015-learning-recall-and-model-trust.md) (learning, recall, requests, model trust).
  - [MEMORY_ARCHITECTURE.md](../MEMORY_ARCHITECTURE.md) Part P6/P7.

## Context

Phase 6 stores people and projects (`memory_entities` with aliases) and facts about them (`memories`). A person's relation to the user is a free-text column (`memory_entities.relation`, "çocukluk arkadaşı"). There is no way to say "Ahmet'in kardeşi Mehmet" as a link between two people, nor to answer "çocukluk arkadaşımın kardeşinin eşi kim?".

The owner's Phase 7 brief asks for:

- typed, evidenced relationships between people, organizations, projects, places, events and groups, and with the user;
- identity checks on **both** ends of every relationship;
- deterministic multi-hop queries (1–3 steps);
- separation of stated facts from derived readings, with time, corrections and conflicts handled;
- merge and split without loss;
- forgetting that leaves no trace, sensitive data kept behind approval;
- learning with Gemma only; chat commands executed before the reply;
- UI and API for all of it;
- measured performance at 100–50,000 relationships;
- 150+ identity scenarios and real-model evaluation.

The governing rule is the brief's own: *LAZIS'in bir ilişkiyi bilmemesi, yanlış bir ilişki kurmasından daha iyidir.*

## Assessment of the Phase 6 code

| Part | Use in Phase 7 |
|---|---|
| `memory_entities`, aliases, `resolver`, namesake inbox, open-question recall | **Reused as is** for both relationship ends. Each end is resolved with the same rules (name + the user's relation words; a pending namesake blocks guessing). |
| `UnitOfWork`, change sets, history, `TRACKED_TABLES` | **Reused.** Relationships are history-tracked like memories. |
| `policy` (secrets, instruction-like text, sensitivity), suppressions (HMAC) | **Extended**: relationship types carry a sensitivity floor; relationship fingerprints. |
| `extraction` (instruction, schema, validation), `learning` (queue, idle start, cancel, re-warm) | **Extended**: the same request also proposes relationships. Same validation discipline (quote, grounded endpoints, user's own relation words). |
| `retrieval` | **Extended**: direct relationships of named entities, plus a deterministic path answer when the message asks along a chain. |
| `commands` | **Extended**: relate / unrelate / correct relation / same person / different people / relation questions. |
| `service.merge_entities` / `split_entity` / `forget_entity` | **Extended** to move, dedupe and delete relationships. |
| `memory_entities.kind` CHECK (no `event`, `group`) | **Changed** by a table rebuild in 0005. This is the one schema change that cannot be done additively. |
| `memory_entities.relation` (free text to the user) | **Kept** as the display label. The user→entity edge becomes a typed relationship; the label stays in sync. |

## Decisions

1. **One more migration, `0005_graph`.**
   - Adds `memory_relationships`, `memory_relationship_evidence` and `memory_entity_distinctions` ("these are different people").
   - Rebuilds `memory_entities` to allow `event` and `group` and to add `is_user`, `confidence`, `origin`. 0004 is frozen: applied migrations are checksum-verified.
   - The rebuild follows SQLite's documented procedure: foreign keys off outside the transaction, rebuild, `foreign_key_check`, foreign keys on. It is enabled per migration by an explicit marker in the runner, after the usual encrypted pre-migration backup.
   - A plain `DROP TABLE` with foreign keys on would cascade-delete every memory: that is why the marker exists, and it is tested.
2. **The user is one fixed entity row** (`id = 'user'`, `is_user = 1`), used only as a relationship endpoint. Memories about the user keep `subject_id IS NULL` (Phase 6 compatibility). The user row is never listed, resolved, merged or forgotten.
3. **Typed relationship vocabulary in code** (`memory/relations.py`), like the predicate registry. Each type has:
   - Turkish labels (forward and inverse);
   - category, symmetric or directed, and its inverse;
   - allowed endpoint kinds;
   - cardinality per source (single / multi);
   - an exclusivity group (kinship types between the same pair exclude each other);
   - sensitivity.

   Semantics: (source, type, target) reads "target is source's ⟨type⟩" for roles ("Mehmet, Ahmet'in kardeşi"), or "source ⟨verb⟩ target" for affiliations ("Ahmet, X'te çalışıyor").
4. **One canonical row per relationship; inverse and symmetric readings are computed at query time, never stored.** Nothing derived is stored, so a corrected or forgotten edge cannot leave stale derived edges behind. Non-invertible types (`knows`) have no inverse reading.
5. **Statuses:**
   - `active` (current), `ended` (past), `planned` (future), `unverified` (the user was unsure);
   - `superseded` (replaced by a correction or a single-valued change), `retracted` (the user said it is not true; kept for audit, never used).

   Times are kept only when the user stated them (`time_text`, plus ISO dates when explicit).
5a. **Conflicts.**
   - A single-valued type with a change signal → the old edge ends.
   - A correction signal ("yanlış söyledim", "aslında") → the old edge is superseded.
   - The same pair with another type from an exclusive group and no signal (sibling vs cousin) → a conflict inbox item; the user decides.
   - Coexisting types (friend + colleague; two employers; two projects) are not conflicts.
6. **Both ends are resolved before anything is written.** An ambiguous end (either one) turns the whole candidate into an inbox question. As built, this is an `ambiguous_entity` item with `payload.target = "relationship"`, so the Phase 6 readers (open questions in recall and extraction) keep working. Nothing is attached until it is answered. The model's identity pick or confidence never decides identity.
7. **Multi-hop answers come from the graph, not the model.**
   - A deterministic Turkish chain parser ("çocukluk arkadaşımın kardeşinin eşi") turns the question into a path from the user or a named entity.
   - Bounded traversal (depth ≤ 3, cycle-free, at most 50 paths) returns every matching path with its edges' statuses.
   - Ambiguous starts, several answers and no path are reported as such.
   - The model only words the result, which is passed as a marked block.
   - Paths use current edges only; sensitive edges only when the question names that type.
8. **Forgetting extends to relationships:**
   - rows, evidence and history content are deleted;
   - an HMAC suppression per (source, type, target) and per pair ("Ahmet ile Zeynep ilişkisini unut") stops re-learning;
   - forgetting a person removes their relationships but not the other people's own facts.
9. **Merge moves relationships** (duplicates folded, evidence kept, self-loops removed and reported). Merging is refused for entities marked distinct. **Split** moves the relationships the user assigns; the others stay. Nothing is moved by guess.
10. **No automatic transformation of old data by guess.** A one-time, deterministic upgrade step turns a Phase 6 relation label into a user relationship only when the label maps exactly to the vocabulary ("çocukluk arkadaşı" → childhood friend). Its counts are logged and shown in diagnostics; everything else stays a label. Old conversations are not scanned.

## Consequences

- One more migration with a table rebuild. It is tested for upgrade, a half-applied run, foreign-key integrity and new installs.
- No `entity_mentions` table yet. Mention-level grounding (moving exactly the knowledge a mention grounded) stays the Phase 0 plan. Split asks the user instead.
- No placeholder entities ("eşimin annesi" without a name): a relationship needs a named target. This is listed as a limitation.
- Kinship composition (parent's sibling = aunt) is not inferred. Only stated types and their inverse/symmetric readings are used.

## As built (Phase 7) — what changed during implementation

The decisions above hold. The real-model gold set (`evals/datasets/relation_gold.json`, 50 cases) found five critical errors in its first run. Each was closed in code, not only in the prompt, and covered by a test (PHASE_7_REPORT §K). The final run had 46/50 cases, no critical errors and no false relationships. The rules added, all in the direction of asking or not storing:

| Rule | Where | Stops |
|---|---|---|
| A sensitive relation label ("sevgilim") never becomes a relationship or a stored label by itself | `relationships.ensure_user_relation`, `service._subject_for`, `policy.decide` | an intimate relationship stored without approval |
| A relationship with the user as one end needs the user in the message (first person); the label shortcut needs the relation said in the first person | `extraction.validate_relations`, `relations.says_mine` | "Selim'in oğlu Arda" stored as the user's child |
| "X'in ⟨noun⟩ Y" fixes a reversed direction (never the type) | `extraction.stated_triples`, `_fix_direction` | parent/child reversed |
| A new kind of user relationship for a stored person asks "same person or another?" | `relationships._maybe_a_namesake` | "İş ortağımın adı da Ahmet" attached to the childhood friend Ahmet |
| Quoted text and messages that try to change the rules teach nothing | `extraction.users_own_words`, `instruction_message` | relationships learned from an e-mail to summarize or a fake system message |
| An uncertain claim needs its type in the user's words | `type_not_stated` | "akraba olabilir" stored as siblings |
| Namesakes are identified by appositives, restated relationships, or the link to the other end | `extraction.appositive`, `relationships._narrow_to_holder` | needless "which Ahmet?" questions and wrong attachments |
| Answers about a name with an open namesake question say so and ask | `graph._with_namesake_caution` | an answer about the stored Ahmet given for the other one |
| A relationship type must be in the user's words (noun or verb); the user's own noun cannot type others; a third-person noun before a name is someone else's | `relations.named_in`, `only_mine`, `extraction.someone_elses` | "kahve içtik" → friend; "Ablam Derya Kaan'la evlendi" → Derya–Kaan siblings; "kardeşimin arkadaşı" → the user's friend |
| Corrections, appositives, counted groups and "X, P projesinde çalışıyor" are read from the user's grammar | `extraction.stated_correction`, `appositive`, `stated_group`, `stated_project_work` | the model's contradictory flags on a correction; missed or reversed relationships |
| Copied relation words do not settle an open namesake question | `extraction.validate(unsettled=…)` | a fact attached to the stored Ahmet with words from an earlier message |
| JSON schemas forbid other keys | `extraction.schema`, `commands.schema` | degenerate invented keys until the token limit |

Two implementation choices worth recording:

* **Finding names.** Names in a message are found by an indexed lookup of only the alias keys that can occur in it, instead of scanning every alias. This cut recall at 50,000 relationships from 14.6 ms to 1 ms, and Phase 6 recall at 50,000 records from 5.5 ms to 0.28 ms.
* **The one-time label upgrade** runs at engine start and is reported in diagnostics. It keeps sensitive labels as labels.
