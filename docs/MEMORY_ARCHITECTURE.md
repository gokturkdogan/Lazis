# LAZIS — Memory and Learning Architecture

> Status: **as built in Phase 7** (Parts P6 and P7 below) · Last updated: 2026-10-20
> The Phase 0 design (sections 1–21, unchanged below) remains the long-term plan; Parts P6 and P7 record what Phases 6 and 7 actually built, where they deliberately differ, and why. Code docstrings refer to the P6/P7 sections.
> Related: [KNOWLEDGE_GRAPH_DESIGN.md](KNOWLEDGE_GRAPH_DESIGN.md), [SECURITY_MODEL.md](SECURITY_MODEL.md), ADR [0014](adr/0014-personal-memory-store.md), ADR [0015](adr/0015-learning-recall-and-model-trust.md), ADR [0016](adr/0016-entity-relationship-graph.md), [PHASE_6_REPORT.md](PHASE_6_REPORT.md), [PHASE_7_REPORT.md](PHASE_7_REPORT.md).

## Part P6 — As built (Phase 6)

### P6.1 Overview and data flow

```
user message ──► stored (+ durable memory job, same transaction)
     │
     ├─ cue check (commands.detect, µs) ──► explicit request? ─► one JSON call on the cached prefix
     │                                         └─► execute (write / forget / confirm) ─► HAFIZA İŞLEMİ notice
     ├─ recall (retrieval.recall, < 1 ms at 10k records) ─► KİŞİSEL HAFIZA block
     │
     └─ reply request = cached prefix + [notice + block + user message]   (block never stored)
                         │
post-turn:  re-warm (joinable) ─► learning job (preemptible): cached prefix + extraction instruction
                         └─► validate ─► policy ─► resolve entity ─► consolidate ─► one change set
```

Modules (`core/src/lazis/memory/`, no single "memory.py"):

| Module | Role |
|---|---|
| `text` | Turkish casing/folding, name keys, prefix terms for FTS5, suffix-tolerant name matching |
| `registry` | predicates: label, cardinality, sensitivity floor, allowed subjects, pinned, search hints |
| `models` | dataclasses (Entity, Memory, Evidence, InboxItem, Job, Candidate, ApplyReport) |
| `repository` | SQL for the memory tables, FTS maintenance, keyed suppression fingerprints |
| `policy` | restricted-data detectors (credentials, tokens, IBAN, TC kimlik, cards, contacts), instruction-like text, save / ask / drop |
| `extraction` | the extraction instruction, JSON schema, validation of model output |
| `resolver` | which person/project a candidate is about (namesakes are asked) |
| `consolidation` | duplicate / supersede / conflict / coexist |
| `service` | applying candidates (one `UnitOfWork` per batch), inbox decisions, forget, edit, merge/split |
| `orchestrator` | DB-side context for extraction (mentioned entities, current facts, forgotten topics, open questions) |
| `retrieval` | recall and the marked block |
| `commands` | explicit requests in chat and their notices |
| `importer` | starting-profile import (JSON, text), preview, apply |

The conversation layer owns the model calls: `conversation/learning.py` (background learning), `ConversationEngine._memory_request` / `_with_memory` (requests and recall in a turn), `import_text_candidates`.

### P6.2 Storage

Migration `0004_memory.sql`, inside the existing SQLCipher database (no second database):

* `memory_entities` (+ `memory_entity_aliases`): people, projects, organizations, places; `status` active/merged (a merged record points to the one it was merged into).
* `memories`: one fact (`subject_id` NULL = the user), predicate, value, sentence, `status` active/superseded/retracted, `origin` stated/requested/confirmed/imported/user_edit/inferred, confidence, importance, sensitivity (+ category), validity (`valid_from`/`valid_to`), `supersedes_id` chain, `conflict_state`, recall count, the creating change set.
* `memory_evidence`: where a fact came from (message id, import batch, user edit, confirmation) and the user's quote.
* `memory_fts`: FTS5, **contentless with real deletes** (`contentless_delete=1`); two columns: `body` (sentence, value, subject names/aliases/relation) and `hints` (predicate label and search words, BM25 weight 0.2). Folded text (`remove_diacritics 2` plus our own folding).
* `memory_inbox`: decisions waiting for the user (ambiguous_entity, conflict, sensitive, destructive, import_batch). Pending candidates live here, never in `memories`, so they are never recalled as knowledge.
* `memory_jobs`: one learning job per user message (`UNIQUE`), status queued/running/done/skipped/deferred/failed, attempts, error code, counts.
* `memory_suppressions`: HMAC-SHA256 fingerprints (key in `app_meta`, inside the encrypted DB) of forgotten or rejected facts/topics — no text.

Every knowledge write is one change set with per-row history (P1 `UnitOfWork`). Memory tables are registered as `TRACKED_TABLES`: history is written, but the generic row revert refuses them (`table_not_revertible`) — a row restore would give a memory a new rowid behind the contentless index and cascade-delete its evidence. Memory changes are undone through forget, edit and inbox decisions.

### P6.3 Predicates

36 predicates in `registry.py` (profile, devices, preferences, time-bound, sensitive, projects, `relationship`, `note`). `single` predicates have one current value per subject (a new value needs a change signal, else the user is asked); `multi` predicates accumulate. `pinned` predicates (`preferred_name`, `communication_preference`) are recalled for every message. Sensitivity is a floor: `health`, `finance`, `contact`, `address` are always sensitive.

### P6.4 Learning (automatic extraction)

* **Durable queue.** `learning.enqueue` runs in the transaction that stores the user message: nothing is lost on a crash, nothing is processed twice. `running` jobs go back to `queued` at startup.
* **On the cached prefix.** After a reply the engine re-warms the prompt (a turn sent meanwhile joins it); after 6 s without a turn (`learn_after_idle_s`) it starts one `memory` background job: the same messages plus one user-role instruction quoting up to 3 queued messages (`[m1] «…»`). Only the instruction (~1,000 tokens) is new prefill. Measured: the next turn still re-processes part of the shared prefix afterwards (sliding-window attention), so the cache is not claimed warm after learning and the engine re-warms the conversation when learning is done. A turn always preempts the job, typing (prepare) cancels it, and jobs go back to the queue.
* **Instruction** (`extraction.RULES`, Turkish): only what the user said; no questions/greetings/temporary states/hypotheticals; quote; never secrets; entity = plain name, relation only if the user wrote it; change signals; three examples. Known people named in the messages (with a few facts), the user's current single-valued facts, forgotten topics and open namesake questions are context.
* **Validation** before anything is written: the quote must occur in the target message (folded, near-verbatim); the entity must be named in the message, in a recent user message, or be a known entity; a relation must be the user's own words (copied relations were the one critical error in the gold set); the predicate must fit the subject; phone/e-mail values become `contact`; short lists in list-like predicates are split. Then `policy.decide` (secret → drop, instruction-like → drop, trivial → drop, sensitive → inbox), resolution, consolidation.
* **Model trust.** `memory.trusted_models` (default: Gemma 4 12B only). Turns answered by another model are queued as `deferred` and processed when a trusted model answers again; explicit requests with an untrusted model are refused with a notice. Decision and data: ADR 0015, PHASE_6_REPORT §D.

### P6.5 Entity resolution

`resolver.resolve` (pure): no stored entity with the name → new; one → that entity unless the stated relation contradicts the stored one (→ ask); several → only the one the relation identifies; otherwise ask. A model's own pick among namesakes is never enough. Relations compare by suffix-tolerant word stems ("arkadaşım" ~ "çocukluk arkadaşı"). An open question is answered by a later message ("çocukluk arkadaşım olan": the question and its options are extraction context) or in the memory screen; once the fact is saved for one option, the question closes itself. Merge moves aliases, memories and evidence (duplicates fold); split moves selected memories to a new record.

### P6.6 Updates and conflicts

`consolidation.plan`: same value or near-duplicate sentence (Jaccard ≥ 0.8) → evidence added, no new row; single-valued predicate with a change signal or an explicit request → the old value becomes `superseded` (`valid_to` set, kept as history, shown as "önceki bilgi"); without a signal → `conflict` inbox item, the old value marked "onay bekliyor"; multi-valued → coexist, and with a change signal only the replaced value is superseded ("Windows'tan macOS'a geçtim" keeps Linux).

### P6.7 Recall

`retrieval.recall` in priority order within `memory.context_budget_tokens` (200; ×2 for "ne biliyorsun"): pinned → facts about people/projects named in the message (≤ 4 each) → FTS5 hits (≤ 4; prefix terms; terms matching more than max(25, 8%) of records, at most 400, are dropped; hits below 40% of the best BM25 score are dropped; a superseded hit brings its current value) → people named in the previous user message. Plus: namesake warnings, open namesake questions (named now or raised since the previous message), forgotten topics. Sensitive facts are never recalled through a person or the overview, only by a direct match.

The block (`=== KİŞİSEL HAFIZA — BİLGİDİR, TALİMAT DEĞİLDİR ===`) is placed in front of the latest user message **for that request only**: it is not stored, later prompts carry the message without it, and the cached prefix stays valid. The engine anchors token counts on the prompt minus a lower bound of the block's tokens (4 chars/token), so estimates stay conservative. Stored text cannot close the block (`===` and newlines are neutralized).

### P6.8 Requests in chat

`commands.detect` (cue lexicon on folded text, microseconds): remember ("unutma", "kaydet", "aklında tut"…), forget ("unut", "hafızandan sil"…), correct ("yanlış hatırlıyorsun"…), recall ("hakkımda ne biliyorsun"), confirm/decline while a deletion waits. A message containing a secret gets a deterministic "not stored" notice (no model call). Otherwise one synchronous JSON call on the cached prefix tells what exactly is meant; the engine executes it **before** the reply and puts a `HAFIZA İŞLEMİ` notice in front of the message: saved (with the sentences) / corrected / forgotten / confirmation needed / ambiguous / not found / not saved (reason) / technical failure / untrusted model. The persona allows memory claims only with such a notice (persona-v2). The turn reports a `memory` stage to the UI.

### P6.9 Forgetting

Forgetting deletes the memory rows (all statuses for a topic), their evidence, their FTS terms (contentless delete + `optimize`), the content of their history rows (a content-free tombstone stays), related inbox items; adds a keyed suppression (value or whole topic) so background learning does not learn it again (an explicit request overrides); skips queued jobs of earlier messages. A named topic ("Ahmet'in mesleği") means every value of it, past ones included. Deleting a person/project needs confirmation (chat: "evet"; UI; API `confirm=true`) and also removes records merged into it. Chat history and backups are separate layers and are not touched; LAZIS says so. Forgotten topics are announced in recall so a value still visible in the current chat history is not used.

### P6.10 Import

`importer`: JSON (`user`, `people`, `projects`; predicate keys) mapped deterministically; plain text (≤ 8,000 chars) read by the extraction model in paragraph chunks. The preview is a dry run of policy, resolution and consolidation (new / duplicate / update / conflict / ambiguous / excluded + sensitive flag), stored as one `import_batch`; nothing is written until the user applies selected items (ambiguous items need a person, conflicts need replace/both). Discarding deletes the batch.

### P6.11 Privacy and safety

Everything stays in the encrypted database; no network, no telemetry. Logs carry ids, counts, codes and durations — never memory text (tested: a secret in a message never reaches a log file). Secrets are never stored, even on request. Memory cannot change identity or rules, grant tools or approvals: it is data in a marked block, instruction-like text is refused at write time, and the persona rules say records are information.

### P6.12 Not built in Phase 6 (from the design below)

Embeddings / sqlite-vec (FTS5 + entities measured sufficient; ADR 0014), the derived profile summary, open loops, the learning review mode (the inbox covers decisions), merging of differently-worded similar preferences, temporal reasoning over `event_time`, relationships between entities (built in Phase 7, Part P7), backfilling old conversations (needs the owner's approval).

## Part P7 — As built (Phase 7): entities and relationships

The governing rule: *LAZIS'in bir ilişkiyi bilmemesi, yanlış bir ilişki kurmasından daha iyidir.* Every step below prefers asking, or not storing, to a guess.

### P7.1 Overview and data flow

```
user message ─┬─ explicit request ("kaydet", "değil", "unut", "aynı kişi", "farklı kişiler")
              │      └─► commands: relations validated like extraction, applied before the reply
              │          ("aynı kişi" → confirmation; "farklı kişiler" → distinction; deterministic)
              ├─ recall: graph.ask(question) ─► computed answer + supporting path ─┐
              │          named people ─► their direct relationships                ├─► KİŞİSEL HAFIZA block
              └─ background learning: the same extraction call now also returns "relations"
                     └─► validate (grammar, grounding, first person, quotes, rules) ─► both ends resolved
                         ─► policy (sensitive → approval) ─► consolidation (time, corrections, conflicts)
```

New modules (`core/src/lazis/memory/`):

| Module | Role |
|---|---|
| `relations` | the vocabulary (51 types), the Turkish lexicon of relation nouns, readings and rendering |
| `graphstore` | SQL for relationships, evidence, distinctions, fingerprints; batched adjacency |
| `relationships` | applying relationship candidates: both ends, policy, time, corrections, conflicts, inbox decisions, forget, merge/split support, the one-time label upgrade |
| `graph` | deterministic queries: the Turkish question parser, chains, paths, neighbours, answers |
| `api/graph.py` | the relationship endpoints |

### P7.2 Vocabulary (`relations.py`)

51 types in seven categories (family, social, work, organization, project, place, event), each with a forward label ("kardeşi"), an inverse label, symmetry, the inverse type, allowed endpoint kinds, single/multi, an exclusivity group (kinship types exclude each other for one pair), a sensitivity floor and the user's words.

* A stored (source, type, target) reads "target is source's ⟨label⟩" for roles ((Ahmet, sibling, Mehmet) → "Mehmet: Ahmet'in kardeşi") and "source ⟨label⟩ target" for affiliations ((Mehmet, works_at, Kervan) → "Kervan: Mehmet'in çalıştığı yer").
* Read from the other end: a symmetric type is itself, a directed role type has its inverse (mother → child), an affiliation has an inverse label; `acquaintance` has no reading from the other end ("Ali Mehmet'i tanıyor" says nothing about Mehmet).
* Families answer for each other only one way: "arkadaşı" finds a childhood friend; the generic `parent` never answers "annesi" (the gender was not stated).
* Intimate types (`partner`, `ex_partner`) are sensitive.
* The lexicon matches relation nouns on folded text with plural, possessive and genitive endings ("kardeşimin", "ablaları", "çocukluk arkadaşım") — never dative/locative, which collide with ordinary words.

### P7.3 Storage (`0005_graph.sql`)

* `memory_relationships`: source, type, target (FK, cascade), qualifier, status, origin, confidence, sensitivity, time text, `valid_from`/`valid_to`, `supersedes_id`, `conflict_state`, change set, version; `CHECK (source_id != target_id)`; indexes (source, status, type) and (target, status, type).
* `memory_relationship_evidence`: the source message and the user's quote, or user edit / confirmation / migration.
* `memory_entity_distinctions`: pairs the user said are different people (merge is refused for them).
* `memory_entities` rebuilt: kinds `event` and `group`; `is_user`, `confidence`, `origin`. The user is one fixed row (`id='user'`, unique), only a relationship endpoint; memories about the user keep `subject_id IS NULL`.
* The rebuild runs with foreign keys off outside the transaction (a runner marker, `-- lazis:foreign-keys=off`), then `foreign_key_check` must be empty, after the usual encrypted pre-migration backup. Tested: upgrade, half-applied run, a rebuild that would break foreign keys, corrupted v4 database (refused, untouched), new install, integrity check.
* **One row per relationship.** Inverse and symmetric readings are computed at query time and never stored, so a corrected or forgotten relationship cannot leave stale derived rows.
* Statuses: `active`, `planned`, `unverified` (current); `ended` (past); `superseded` (replaced by a correction); `retracted` (the user said it is not true — kept for audit, never used).

### P7.4 Identity: both ends

Both ends of every relationship are resolved before anything is written, with the Phase 6 resolver and these Phase 7 rules:

1. An ambiguous end (either one) turns the whole relationship into a "Hangi Ahmet?" inbox item (`ambiguous_entity`, `payload.target = "relationship"`); nothing is attached until it is answered.
2. A namesake is identified only by the user's words:
   * the stated relation ("iş ortağım Ahmet");
   * an appositive in the message ("çocukluk arkadaşım Ahmet'in kızı");
   * restating a relationship the user already has with one of them;
   * for a denial, end or correction, being the one who holds a relationship with the other end.
3. A **new kind** of relationship between the user and a stored person who is already something else to the user ("İş ortağımın adı da Ahmet" while Ahmet is a childhood friend) asks "same person or another Ahmet?". It never attaches silently.
4. A name with an open namesake question blocks attaching (Phase 6 rule), and graph answers about that name say so and ask.
5. Kinds must fit the type ("Pusula projesinde" is a project, never a colleague); the user is never merged, forgotten or listed.
6. "Bu iki Ahmet farklı kişiler" records a distinction; "aynı kişi" asks for confirmation, then merges (refused after a distinction).

192 deterministic identity scenarios cover single, two and three namesakes, surnames, aliases, Turkish letters, open questions, distinctions, splits, merges, kinds, the user, both ends, relation forms, name forms and structure (`tests/integration/test_identity_scenarios.py`).

### P7.5 Learning relationships (Gemma only)

The Phase 6 extraction call also returns `relations` (source, type, target, relation words, negated, correction, change, status, certain, time). Rule 12 of the instruction defines direction with examples and forbids chains; the type list is part of the instruction (~6 k characters). The same model trust applies: Gemma only; Qwen turns are deferred.

Validation, in order — each failure drops the relationship and is counted:

* The quote must be the user's, and outside quoted text (`quoted_text`): an e-mail to summarize is someone else's words.
* A message that tries to change the rules teaches nothing (`instruction_message`).
* The type must exist; an uncertain claim needs its type named in the user's words (`type_not_stated`: "akraba olabilir" is not "kardeş").
* "X'in ⟨noun⟩ Y" in the message fixes a reversed direction (`direction_fixed`); a different type is left as the model's claim.
* Both ends must be named in the message, recent messages or known context; kinds follow the message's nouns.
* A relationship with the user as one end needs the user in the message (first person) (`user_not_in_message`).
* A Phase 6 `relationship` item becomes a user relationship only when its words map to the vocabulary.
* A relationship type must be in the user's words (a noun, or a verb that states it: "evlendi", "boşandılar", "tanıyor", "çalıştık") (`type_not_stated`). When "X'in ⟨noun⟩ Y" names a type for the pair, the user's noun decides (`type_fixed`). A noun the user says only in the first person ("Ablam Derya …") cannot type a relationship between two others (`type_is_the_users`).
* A relation noun right before a name in the third person ("kardeşimin arkadaşı Yiğit", "Selim'in oğlu Arda") is someone else's, not the user's (`someone_elses`). A relation noun is never a name ("Kızım" ≠ a person named Kız).

The user's grammar also adds what the model left out or got wrong:

* corrections "X aslında Y'nin A'sı değil, B'si" / "X Am değil, Bm" are parsed and replace the model's proposals for that pair, in chat requests and in background learning;
* a first-person appositive ("Kuzenim Selim'in …") becomes that user relationship and fixes a reversed one ("Yöneticim Banu");
* a counted or plural first-person noun ("iki arkadaşım", "arkadaşlarım") is shared by the names listed with it, next to the model's own reading of the group;
* "X, P projesinde … çalışıyor" states X works_on P.

Relationships and facts are kept consistent:

* a user's lives_in / works_at relationship is also the location / employer fact, and an employer fact is also a works_at relationship;
* a fact that only restates a relationship of the same message is not stored twice;
* a fact whose subject is its own value is dropped.

The JSON schemas forbid other keys (`additionalProperties: false`). The prompt examples are disjoint from every evaluation set (an earlier overlap was found and removed; PHASE_7_REPORT §K).

The label shortcut (a person's relation words → the typed user relationship) needs the relation said in the first person ("kuzenim Selim", not "Selim'in oğlu"). It never creates a sensitive type or stores a sensitive label.

### P7.6 Deterministic queries (`graph.py`)

* **Parser.** Turkish questions become typed queries:
  * chains: "çocukluk arkadaşımın kardeşinin eşi kim", "Ahmet'in kardeşi Mehmet'in eşi", "annemin adı ne", "kardeşi Mehmet mi?";
  * paths: "Zeynep'i nereden tanıyorum", "Ahmet ile Zeynep arasında", "evli mi", "Mehmet, Ahmet'in neyi oluyor";
  * neighbours: "kimlerle bağlantısı var", "ailesi hakkında", "ailem";
  * affiliations: "Pusula projesinde kim çalışıyor", "nerede çalışıyor", "hangi projede";
  * "Zeynep kim?".

  Names come from the alias index (indexed lookup of only the keys that can occur in the question). Unknown capitalized names are reported as unknown. Statements are not questions.
* **Walks.** Bounded:
  * at most 3 steps, cycle-free (no person twice);
  * at most 50 paths and 200 relationships per person;
  * paths meet in the middle (two levels from one end, one from the other);
  * current relationships only (a failed chain also checks ended ones and reports them as past).
* **Sensitive relationships** appear only when the question names that type — never in paths, neighbour lists or the map.
* **Answers:**
  * unique / several, each with its supporting path;
  * none, with where the chain broke ("Bilinen: … ; Mehmet'in annesi kayıtlı değil");
  * ambiguous ("which Ahmet?");
  * unknown.

  The model only words the answer.

### P7.7 Recall

`retrieval.recall` puts the graph's answer first, after pinned memories, as "İlişki sorusu (kayıtlı ilişkilerden hesaplandı; burada olmayan bir ilişkiyi ekleme, tahmin etme)". People named in the message bring up to 4 direct current relationships each, and the overview ("hakkımda ne biliyorsun") lists up to 10 of the user's own. All of this stays within the same budget. An unknown name is mentioned only for a personal question ("Burak'ın kardeşi"), not for general knowledge ("Google'ın patronu"). The persona prompt adds one sentence: answer relationship questions from the computed answer, and infer no kinship or acquaintance.

### P7.8 Requests in chat

| What the user says | What happens |
|---|---|
| "kaydet: …" | relationship facts are written via the existing request call, with a `relations` field validated like extraction |
| "X Y'nin kardeşi değil", "… değil, kuzeni" | the relationship is denied or corrected; detected from relation noun + "değil", not a question |
| "X ile Y arasındaki ilişkiyi unut" | one type, or the whole pair, is forgotten (forget scope `relation`) |
| "aynı kişi" | deterministic; the merge waits for "evet" |
| "farklı kişiler" | deterministic; recorded as a distinction |

The `HAFIZA İŞLEMİ` notice lists exactly what changed in the graph: created, retracted ("artık geçerli değil"), moved to history.

### P7.9 Time, corrections, conflicts

* **Change signals** ("artık", "ayrıldı", "geçti"):
  * single-valued types and workplaces → the old relationship ends (`valid_to`);
  * "artık … çalışmıyorum" ends a relationship — it never retracts it.
* **Correction signals** ("aslında", "yanlış söyledim") → the old one is superseded (history kept).
* **Denial** → retracted plus a rejection suppression.
* **Conflicts:**
  * another kinship for the same pair without a signal → a conflict inbox item;
  * coexisting types (friend and colleague, two projects) are not conflicts.
* **Time and status:**
  * planned relationships are current but marked;
  * uncertain ones are `unverified`;
  * stated times are kept as text.

### P7.10 Forgetting and privacy

* Forgetting a relationship deletes the row, its evidence and its history content. It adds HMAC suppressions per relationship and, for a pair, per pair, so neither is learned again; an explicit request overrides.
* Forgetting a person removes their relationships, but not the other people's facts.
* Multi-hop answers, paths, the map and recall never run through a forgotten link (tested).
* Sensitive relationships need approval: an inbox item, or an explicit request. Logs carry counts and codes only (tested: no names or relation words in logs).

### P7.11 Merge and split

* **Merge:**
  * relationships move to the kept record;
  * relationships between the two records become self-loops and are removed and reported;
  * equivalent duplicates are folded, keeping their evidence;
  * refused for a distinct pair.
* **Split:** moves the relationships the user assigns and records a distinction.

### P7.12 API and UI

* **API** (`/api/v1/memory`):
  * `relationship-types`;
  * `entities/{id}/relationships` (also `user`; read from that side, current and past);
  * `relationships/{id}` (evidence, earlier versions), `POST relationships`, `PATCH`/`DELETE relationships/{id}`;
  * `graph/neighbourhood/{id}?depth=1|2&past=` (bounded, non-sensitive), `graph/paths?from=&to=`;
  * relationship and merge decisions in `inbox`.
* **UI** (Hafıza → Kişiler ve projeler):
  * the user's own relationships first;
  * per person: relationships with reading, status, time, conflicts, origin, evidence and earlier versions;
  * add with only the types that fit both kinds, edit, delete after confirmation;
  * a simple SVG relation map (depth 1–2, past optional);
  * the inbox marks relationship decisions and confirms or rejects merges.

### P7.13 Performance

Measured in `evals/runners/p7_perf.py` (production code, encrypted database on disk). At 50,000 relationships, p95:

| Query | Time (p95) |
|---|---|
| Direct | 0.15 ms |
| Two steps | 1.2 ms |
| Three steps | 1.8 ms (a wide fan-out: 4.5 ms) |
| Paths | 1.4 ms |
| Recall with a relationship question | 1.2 ms |
| One write | 0.8 ms |

Names in a message are found by an indexed lookup of only the keys that can occur in it, so recall no longer scans every alias (Phase 6 recall at 50,000 records: 5.5 → 0.28 ms p50). Details and chat latency: PHASE_7_REPORT §I.

### P7.14 Not built in Phase 7

* placeholder entities for unnamed people ("eşimin annesi" needs a name);
* kinship composition (parent's sibling = aunt is never inferred);
* mention-level grounding (`entity_mentions`);
* relationship import in the starting-profile importer;
* the event/group screens beyond the generic person detail;
* backfilling relationships from old conversations (not scanned; needs the owner's approval).

## Part P7.1 — As built (Phase 7.1): truthful memory claims

Decision record: [ADR-0017](adr/0017-truthful-memory-claims.md). Report: [PHASE_7_1_REPORT.md](PHASE_7_1_REPORT.md).

A reply may say that LAZIS saved, deleted or updated something only when that operation really happened in the turn. The model's notice asks for this; `lazis.memory.claims` enforces it on the reply text.

* **State.** `claims.state_for` maps the turn's explicit request and its executed outcome (`commands.Outcome.kind`, known before the reply starts) to a `ClaimState`: `save_/update_/delete_succeeded`, `save_/delete_pending` (waiting for the user), `save_/update_/delete_failed`, `auto_learning_pending` (a statement; background learning runs after the reply), `no_memory_action`. A `Policy` adds whether recall brought stored memory (references to existing records need it) and whether the turn is a memory request.
* **Rules.** Deterministic Turkish rules on folded text, sentence by sentence: first person completed or committed memory acts are claims (including note/record nouns with possessive endings, "notunuzu aldım", and storage nouns, "listeme ekledim"); negation, inability, offers, questions, other persons, quotations, mentions ("not aldım gibi") and "nothing stored" are not; first person participles and passives ("kaydettiğimiz", "kaydedilmiş") are references to existing records. Delete/update verbs are memory acts only near a memory word or in a memory request.
* **Rewording.** Only the claim: pending → "anladım" (or the redundant clause dropped after an acknowledgement), failure → "kaydedemedim / silmedim / güncelleyemedim", waiting → "henüz kaydetmedim / henüz silmedim"; an unrecalled reference to a record points at the conversation ("konuştuğumuz").
* **Streaming.** `ClaimGuard` sits between the model stream and every consumer. It releases text with a one-word lag, holds from the first word that could begin a claim to the end of that sentence (240 characters at most), and never takes back released text. The engine stores `guard.released` — the done message, partial flushes, and cancelled or failed replies are what the user saw; the voice pipeline must read the same text.
* **Diagnostics.** Last turn: `claim_state`, `claims_rewritten`, `first_shown_ms`. Log event `memory.claims_rewritten` with state, count and kinds only.
* **Unchanged.** Learning (extraction policy, queue, background timing), the graph, recall, the schema, and the model notices.

## Part P7.2 — As built (Phase 7.2): namesakes, explicit requests, internal labels

Decision record: [ADR-0018](adr/0018-namesakes-and-explicit-requests.md). Report: [PHASE_7_2_REPORT.md](PHASE_7_2_REPORT.md).

* **Namesakes in one message** (`memory/namesakes.py`). Counted names and their slots ("İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım", "Üç Ayşe: kuzenim, komşum ve iş arkadaşım", "Ahmet adında iki arkadaşım") and one person with several roles ("hem … hem") are read from the user's words. Before anything is written, each candidate gets its slot's entity (`EntityRef.planned`): a stored namesake the slot identifies, or a new one. Slot entities are marked as different people; a slot the model left out is still created; a candidate fitting no slot goes to the resolver, which asks. Runs in background learning and explicit requests.
* **"Which Ahmet?" in chat.** An ambiguous request's notice lists the options. A short answer within 30 minutes in the same conversation ("Komşum olan.", "Mühendis olan Mehmet.") resolves the waiting inbox item through `service.resolve_inbox` before the reply; "vazgeç" dismisses it; "Hayır, iş arkadaşım olan." right after an answer moves the fact (in-memory, last answer only). Older questions stay in the memory screen; nothing is guessed after a restart.
* **Explicit remember.** The request stage uses the learning instruction plus an explicit-request note and an `action` field (`commands.remember_instruction`). "Bunu unutma." alone keeps the previous user message. Wider cue lexicon; quoted text is not a request. Validation: a non-name subject is the user's note, never one of the user's profile facts; a single-valued user profile fact needs a first-person word; a valid quote under a wrong predicate is kept as a note; something already recorded is reported as kept.
* **User's grammar.** "Ahmet ve Mehmet benim iş arkadaşlarım" gives both names the relationship (`extraction.stated_predicate`); a self-valued workplace in a first-person message is the user's. With an open "which Ahmet?" question, relationship answers about Ahmet are withheld until the user says which one (`graph._with_namesake_caution`).
* **Internal labels.** The persona and conversation rules name no internal label; notes are headed "SİSTEM NOTU (kullanıcıya görünmez)" and said to be invisible; the persona gives the honest answer about what LAZIS remembers. No output filter.
* **Unchanged.** Extraction policy and prompt for background learning, the queue and its timing, the graph's storage and queries, recall, the schema (no migration), the Phase 7.1 claim guard.


## Part P8 — As built (Phase 8): personal knowledge bootstrap

Decision record: [ADR-0019](adr/0019-personal-knowledge-bootstrap.md). Report: [PHASE_8_REPORT.md](PHASE_8_REPORT.md).

**Pipeline** (`core/src/lazis/bootstrap/`):

| Module | Does |
|---|---|
| `files.py` | name → format (`.md`/`.markdown`, `.txt`, `.json`); ≤ 1 MB, ≤ 200,000 characters; UTF-8 (± BOM) or UTF-16 with BOM; NUL/binary refused; control characters dropped; secret lines redacted; Markdown sections by heading path, text by paragraph (≤ 1,400 characters), every line keeping its file line; base name only |
| `profile.py` | JSON schema 1.0 (`profile`, `people`, `relationships`, `projects`, `preferences`, `habits`, `goals`, `events`, `facts`; all optional; Turkish/English key names; the Phase 6 `user` shape) → proposals; unknown parts become warnings, a name shared by two people is never guessed |
| `extract.py` | one model call per section with the learning instruction and an import note; learning's validation (quote in the section, names in the section, relation words the user's); predicate check against the quote; people assembled across the file from the user's words (`namesakes.stated`, "hem … hem", relation-compatible joins only) |
| `analyze.py` | dry run: each proposed person matched (new / existing suggestion / ambiguous) and each item classified (`new`, `exact_duplicate`, `possible_duplicate`, `conflict`, `temporal_update`, `ambiguous_entity`, `insufficient_evidence`, `excluded`); import-only directive check |
| `store.py` | the draft: batches, sections, people, items, decisions, re-classification when a person is decided, summary, save states |
| `apply.py` | final check, then one `UnitOfWork` (kind `import`): people, distinctions, facts, relationships, `rejected` suppressions, item results, counts |
| `undo.py` | plan from the apply change set's history and evidence; one `UnitOfWork` (kind `rollback`) |
| `pipeline.py` | JSON start, text finish, discard, earlier rejections of the same file |
| `conversation/bootstrap_runner.py` | the model side: background jobs (kind `import`), preemption, cancel, split on truncation |

**Database** (migration `0006_bootstrap`, additive; no existing table changed):

* `import_batches` — one import: `status` (`analyzing` → `ready` → `applied` → `undone`; or `failed`, `cancelled`, `discarded`), file name, format, content hash, size, section counters, model, model calls, error code, warnings, `counts_json` (what the write did; `undo` inside it after an undo), `effects_json` (distinctions and suppressions it added), apply/undo change set ids.
* `import_sections` — the redacted text of each section and the model's answer while analysing; set to NULL when the import is applied, cancelled or discarded.
* `import_people` — proposed people: name, kind, relation, description, match, options (stored namesakes and file namesakes), suggestion, decision (`pending`/`create`/`link`/`unresolved`/`reject`), link target, the entity written.
* `import_items` — proposed facts and relationships: payload, refs to proposed people, source section / excerpt / line, method (`json`/`gemma`), confidence, classification, stored values compared with, note, decision (`pending`/`approve`/`reject`/`hold`), resolution (`keep_old`/`update`/`keep_both`), edited value, result, written ids.
* Written records carry evidence `source_type = 'import'`, `source_ref = <item id>`; the change set's `source_ref` is the import id.

**API** (`/api/v1/memory/bootstrap`, schemas in `api/bootstrap_schemas.py`):

| Route | |
|---|---|
| `POST /analyze` | `{file_name, content_base64}` → batch; JSON is `ready` at once, Markdown/text `analyzing` (the only route with a larger body: 1.45 MB) |
| `GET /` | earlier imports (not discarded) |
| `GET /{id}` | batch (+ progress), people, items (with `blocked` and `save_state`), summary |
| `POST /{id}/cancel` · `POST /{id}/retry` | stop and delete the draft · read failed (or interrupted) sections again |
| `POST /{id}/decisions` | `{people: [{id, decision, link_id}], items: [{id, decision, resolution, edited_value}]}` → preview |
| `POST /{id}/apply` | one transaction → batch with counts and the change set id |
| `GET /{id}/undo-plan` · `POST /{id}/undo` | the plan · `{restore: [ids]}` → batch, plan carried out, rollback change set (null when already undone) |
| `DELETE /{id}` | discard a draft that was not written |

Refusals have their own codes (`import_<reason>`, e.g. `import_needs_resolution`, `import_memory_changed`, `import_profile_invalid_json` with `details.line`/`column`); the error body gained an optional `details` object. The Phase 6 `/memory/import/*` routes still work; the UI no longer uses them.

**Recall (condition E).** `retrieval.recall` leaves out the facts and relationships of people the message does not tell apart (namesakes without relation words that settle one, or a name with an open "which one?" question), in the current message and the previous one; the namesake list stays, so the reply asks.

**Unchanged.** Background learning, its prompt and policy, the claim guard (Phase 7.1), namesake planning in chat (Phase 7.2), the graph's storage and queries.


## Part P9 — As built (Phase 9): advanced automatic learning

Decision record: [ADR-0020](adr/0020-advanced-learning.md). Report: [PHASE_9_REPORT.md](PHASE_9_REPORT.md).

**Pipeline** (background learning; explicit requests share steps 3–5):

```
1 extraction (one model call, on the conversation's cached prefix)
2 JSON salvage if the answer broke near its end            extraction.salvage
3 validation (unchanged: quote, names, relation words)     extraction.validate*
4 list completeness: one focused re-read per partly read list (≤ 2 per job)   lists
5 refinement: tense, change words, time phrase, someone else's relatives,
  passing states; pending corrections ("X değil Y") applied   refine, temporal, corrections
6 namesake planning (Phase 7.2), then the write              namesakes, orchestrator, service
```

| Module | Does |
|---|---|
| `memory/temporal.py` | clauses (not split inside lists), tense of a clause (past / current / future), change words, the user's time phrase (never a date) |
| `memory/refine.py` | past → history (`Candidate.tense = "past"`), future → plan, relationship status from the words, change flag only with change words, `event_time` from the user's words, `parent_sibling` / someone else's relatives, passing states dropped |
| `memory/lists.py` | lists and stated counts in the user's words; gaps; the focused re-read instruction; keep only the missing members; count notes |
| `memory/corrections.py` | "Hayır, X değil Y": subject move / rename, value correction, ask when Y is several people or still being placed, wait for an unlearned message |
| `memory/importance.py` | five tiers, computed |
| `memory/quality.py` | prioritised suggestions: conflict, duplicate, stale, ambiguous person, no evidence, uncertain; dismiss |
| `service.apply_one` | `tense == "past"`: history record or end the current same value; duplicates: same source → no new evidence, other sources → confidence +0.03 per source (≤ 0.95) |
| `repository.add_evidence` | one piece of evidence per (memory, source type, source ref) |
| `orchestrator.extraction_context` | also shows stored preferences / habits that share a word stem with the message |

**Database:** migration `0007_quality` (additive): `memory_quality_dismissed (fingerprint PRIMARY KEY, kind, created_at)` — a content-free fingerprint of a hidden suggestion. No other table changed; history values are ordinary `superseded` rows with `valid_from` NULL.

**API** (`/api/v1/memory`):

| Route | |
|---|---|
| `GET /quality?limit=` | prioritised suggestions: `id`, `kind`, `priority`, `subject`, `title`, `memory_ids`, `entity_ids`, `values` |
| `POST /quality/{id}/dismiss` | `{kind}` → hide it (returns the remaining list) |
| `GET /records?new_days=N` | learned in the last N days (1–90), newest first |
| record model | new fields `tier` and `sources` (independent sources) |

**Chat:** "Hayır, X değil Y (demek istedim)" is a deterministic memory request (outcome `corrected` / `ambiguous`; the reply is told what really happened). "Hayır, vazgeç" calls off a waiting "which one?".

**Unchanged:** the policy (secrets, instructions, sensitive → approval), the claim guard (Phase 7.1), namesake planning and "which one?" (Phase 7.2), the graph's storage and queries, recall (besides tiers in the record model), the import (Phase 8; it now also salvages broken answers).

---

# Phase 0 design (long-term plan)

## 1. Design goals

1. **Correct before complete.** A false memory is worse than a missing one. Every stored fact is traceable to evidence.
2. **Autonomous but accountable.** LAZIS learns ordinary information on its own, without asking. **Risk**, not habit, decides when it asks. Every automatic decision is recorded with its reasons and can be reviewed and undone.
3. **Never fabricate.** LAZIS asserts only what is stored with evidence. Uncertain knowledge is stored and spoken as uncertain. Missing knowledge is admitted, never filled in.
4. **User sovereignty.** Everything is inspectable, correctable, reversible and deletable, with predictable effects on dependent knowledge.
5. **Temporal truth.** Facts change ("İzmir'de yaşıyorum" → "Ankara'ya taşındım"). The system keeps when a fact was true, not only what is true now.
6. **Simple infrastructure.** One SQLite database (`lazis.db`) holds structured data, FTS5 indexes and sqlite-vec vectors. No extra servers.
7. **Fast recall.** Retrieval ≤ 80 ms p95 *(target, unmeasured)*, so it never dominates turn latency.
8. **Evolvable.** Versioned schema (migrations), versioned embeddings (re-index), versioned prompts and policies (hash stamps).

## 2. Memory taxonomy

| Kind | Cognitive analogue | Example (Turkish surface) | Typical subject | Cardinality |
|---|---|---|---|---|
| `fact` | semantic | "Ayşe hemşire olarak çalışıyor." | any entity | per predicate |
| `preference` | semantic | "Kahveyi şekersiz içiyor." · "Kısa cevapları seviyor." | user / person | multi |
| `event` | episodic | "2024 Haziran'da Ankara'ya taşındı." | user / person | multi, dated |
| `plan` | prospective | "Ahmet yeni bir şirket kurmayı düşünüyor." | user / person | multi, temporal |
| `episode` | episodic | Summary of a conversation segment | conversation | — |
| `relationship_note` | social | "Can'la arası son zamanlarda gergin." | relationship | multi, temporal |
| `project` | semantic + episodic | "LAZIS projesi: kişisel yapay zekâ asistanı." | project entity | — |
| `goal` / `dream` | prospective | "2027'de maraton koşmak istiyor." | user | multi |
| `instruction` | procedural | "Bana sabahları uzun mesaj atma." | LAZIS behavior | multi |
| `open_loop` | prospective | "Cuma günü iş görüşmesi var → sonucunu sor." | user | stored in `open_loops` |
| `profile_summary` | semantic (derived) | Regenerated compact profile | user | 1 (cache) |

A `plan` is deliberately separate from a `fact`. "X'i düşünüyor" or "X yapacak" is stored as an intention with its own validity, never as an accomplished fact.

## 3. Knowledge placement rule

One piece of knowledge has exactly one home. This removes the Phase 0 overlap where `works_at` and `lives_in` existed both as memory predicates and as graph relationships.

| Knowledge shape | Home | Examples |
|---|---|---|
| **Entity ↔ entity** | `relationships` (graph) | friend_of, sibling_of, spouse_of, works_at (with `title` attribute), lives_in, member_of_project, participated_in |
| **Entity → literal** (attribute, preference, event, plan, note) | `memories` | likes, birth_date, health_condition, plan, goal, note |
| **Free-form narrative** | `memories` (`predicate = note`, `kind = episode` or `relationship_note`) | segment summaries, nuanced notes |
| **Document content** (not yet personal knowledge) | `documents.db` + `document_claims` | see [LOCAL_INGESTION_ARCHITECTURE.md](LOCAL_INGESTION_ARCHITECTURE.md) |
| **Web research** | `cache.db` research tables | never personal memory ([RESEARCH_ARCHITECTURE.md](RESEARCH_ARCHITECTURE.md)) |

Memories and relationships share **one lifecycle model**: the same statuses, confidence, evidence, history, change sets and learning policy. The learning pipeline emits typed candidates (`MemoryCandidate`, `RelationshipCandidate`, `AliasCandidate`, `EntityCandidate`) through the same policy engine.

## 4. Predicate registry (`config/predicates.yaml`)

Predicate semantics drive deduplication, contradiction handling and risk, so they are configuration, not code. Relationship types carry the same policy fields in `config/relationships.yaml` (see the KG design).

```yaml
birth_date:       { cardinality: single, temporal: false, sensitivity: personal,  impact: medium, object: date }
likes:            { cardinality: multi,  temporal: true,  sensitivity: normal,    impact: low,    object: value }
dislikes:         { cardinality: multi,  temporal: true,  sensitivity: normal,    impact: low,    object: value }
hobby:            { cardinality: multi,  temporal: true,  sensitivity: normal,    impact: low,    object: value }
skill:            { cardinality: multi,  temporal: true,  sensitivity: normal,    impact: low,    object: value }
plan:             { cardinality: multi,  temporal: true,  sensitivity: personal,  impact: low,    object: value }
goal:             { cardinality: multi,  temporal: true,  sensitivity: personal,  impact: medium, object: value }
health_condition: { cardinality: multi,  temporal: true,  sensitivity: sensitive, impact: high,   object: value }
financial_status: { cardinality: multi,  temporal: true,  sensitivity: sensitive, impact: high,   object: value }
communication_pref: { cardinality: multi, temporal: true, sensitivity: normal,    impact: low,    object: value, scope: lazis_behavior }
note:             { cardinality: multi,  temporal: false, sensitivity: inherit,   impact: low,    object: value }
```

Unknown predicates proposed by extraction are mapped to the nearest registered predicate (embedding similarity over predicate descriptions). Failing that, the claim is stored as a `note`. New predicates are added deliberately through config changes, which are hash-stamped (§20).

## 5. Data model

### 5.1 Overview

```mermaid
erDiagram
    conversations ||--o{ messages : has
    conversations ||--o{ segments : split_into
    change_sets ||--o{ history : groups
    memories ||--o{ evidence : cites
    relationships ||--o{ evidence : cites
    memories ||--o{ memory_entity_links : grounded_by
    memory_entity_links }o--|| entities : refers_to
    memory_entity_links }o--o| entity_mentions : via_mention
    memories ||--o{ memory_dependencies : depends_on
    memories ||--o| memory_vec_v1 : embedded_as
    memories ||--o| memory_fts : indexed_as
    memories ||--o{ open_loops : spawns
    inbox_items }o--o| memories : about
```

### 5.2 Schema evolution by phase

| Migration (lazis.db) | Phase | Tables |
|---|---|---|
| `0001_system` | P1 | `schema_migrations`, `settings`, `jobs`, `change_sets`, `history`, `audit_log` |
| `0002_conversations` | P3 | `conversations`, `messages`, `segments` |
| `0003_assistant_timeline` | P3 (addendum, ADR-0011) | `messages.timeline_seq`, `messages.channel`; one active technical session. Later migrations below shift by one number |
| `0004_personality` (planned `0003`) | P5 | `response_openers` (anti-repetition store) |
| `0004_memory` | P6 | `entities` (core columns; the user entity), `memories`, `evidence`, `memory_vec_v1`, `memory_fts`, `suppressions` |
| `0005_graph` | P7 | `entities` (+ graph columns), `entity_aliases`, `relationship_types`, `relationships`, `entity_mentions`, `memory_entity_links`, `entity_operations`, `entity_distinctions`, `inbox_items` |
| `0006_bootstrap` | P8 | `import_batches`, `import_items` |
| `0007_learning` | P9 | `learning_runs`, `open_loops`, `memory_dependencies`; review columns |
| `0008_adaptation` | P10 | `preference_signals` |
| `0009_sources` | P11 | `sources`, `source_files`, `document_claims` (the chunk index lives in `documents.db`) |
| `0010_research` | P12 | research audit fields (the cache lives in `cache.db`) |
| `0011_voice` | P13 | `voice_profiles`; `messages.interrupted`, `messages.spoken_text` |

Before P7, a memory about someone other than the user stores the raw reference in `subject_text`. A P7 migration job resolves these through the entity resolver (same policy as everything else).

### 5.3 Key tables (indicative DDL; migrations are authoritative once written)

```sql
CREATE TABLE memories (
  id               TEXT PRIMARY KEY,            -- ULID
  kind             TEXT NOT NULL,               -- fact|preference|event|plan|episode|relationship_note|project|goal|dream|instruction
  subject_id       TEXT REFERENCES entities(id),
  subject_text     TEXT,                        -- unresolved reference (pre-P7 or ambiguous)
  predicate        TEXT NOT NULL,               -- registry predicate or 'note'
  object_value     TEXT,                        -- literal value (normalized)
  content          TEXT NOT NULL,               -- canonical Turkish sentence
  content_norm     TEXT NOT NULL,               -- Turkish-casefolded
  content_fold     TEXT NOT NULL,               -- diacritic-folded (ş→s, ı→i …)
  content_stem     TEXT NOT NULL,               -- Snowball-Turkish stems
  domain           TEXT NOT NULL DEFAULT 'personal',  -- personal|project
  status           TEXT NOT NULL,               -- provisional|active|pending_confirmation|superseded|retracted|archived
  confidence       REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
  risk_level       TEXT NOT NULL,               -- low|medium|high (at last decision)
  importance       REAL NOT NULL DEFAULT 0.5,
  sensitivity      TEXT NOT NULL,               -- normal|personal|sensitive (restricted is never stored)
  trust_class      INTEGER NOT NULL,            -- T0..T5 of the strongest supporting evidence (SECURITY_MODEL §4)
  origin           TEXT NOT NULL,               -- explicit|extracted|imported|user_edit|document|inferred|research_promoted
  review_state     TEXT NOT NULL DEFAULT 'unreviewed', -- unreviewed|approved|corrected
  conflict_state   TEXT NOT NULL DEFAULT 'none',       -- none|pending
  decision_json    TEXT NOT NULL,               -- policy decision: level, confidence components, risk factors, reason codes
  valid_from TEXT, valid_to TEXT, time_precision TEXT,  -- domain time (day|month|year|approx|unknown)
  observed_at      TEXT NOT NULL,               -- when LAZIS learned it
  supersedes_id    TEXT REFERENCES memories(id),
  created_change_set_id TEXT NOT NULL REFERENCES change_sets(id),
  version          INTEGER NOT NULL DEFAULT 1,
  last_recalled_at TEXT, recall_count INTEGER NOT NULL DEFAULT 0,   -- ranking only (§7.6)
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX ix_mem_subject_pred ON memories(subject_id, predicate, status);

CREATE TABLE evidence (                -- provenance for memories, relationships, aliases, entities
  id TEXT PRIMARY KEY,
  target_type TEXT NOT NULL,           -- memory|relationship|alias|entity
  target_id TEXT NOT NULL,
  source_type TEXT NOT NULL,           -- message|import_item|document_chunk|user_edit|user_confirmation|research_promoted
  source_ref TEXT NOT NULL,            -- message id / import item key / chunk id / inbox item id
  quote TEXT,                          -- verbatim span (redactable)
  mention_id TEXT,                     -- entity mention that grounded the resolution (P7+)
  trust_class INTEGER NOT NULL,        -- T0..T5
  independent_group TEXT,              -- corroboration grouping key (segment/day/source)
  extractor TEXT, prompt_version TEXT, policy_version TEXT,
  change_set_id TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX ix_evidence_target ON evidence(target_type, target_id);

CREATE TABLE change_sets (             -- every write belongs to exactly one change set
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,                  -- explicit_command|learning_run|import|user_edit|review_action|merge|split|
                                       -- document_ingest|correction|deletion|rollback|migration
  actor TEXT NOT NULL,                 -- user|pipeline|import|system
  source_ref TEXT,                     -- segment id / import batch / source file / inbox item
  summary TEXT NOT NULL,               -- content-free description ("3 hafıza, 1 ilişki")
  reverts_change_set_id TEXT REFERENCES change_sets(id),
  status TEXT NOT NULL,                -- applied|partially_reverted|reverted
  created_at TEXT NOT NULL
);

CREATE TABLE history (                 -- append-only version log for memories, relationships, entities, aliases
  target_table TEXT NOT NULL, target_id TEXT NOT NULL, version INTEGER NOT NULL,
  change TEXT NOT NULL,                -- create|update|status_change|supersede|reassign|merge|split|delete|restore
  change_set_id TEXT NOT NULL REFERENCES change_sets(id),
  before_json TEXT, after_json TEXT,   -- purged to NULL on hard delete (tombstone keeps only ids + change)
  at TEXT NOT NULL,
  PRIMARY KEY (target_table, target_id, version)
);

CREATE TABLE memory_entity_links (     -- which entity each memory is about, and through which mention
  memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  role TEXT NOT NULL,                  -- subject|object|mentioned
  entity_id TEXT NOT NULL REFERENCES entities(id),
  mention_id TEXT,                     -- grounding mention (enables precise correction propagation)
  resolution TEXT NOT NULL,            -- self|confirmed|linked|tentative
  confidence REAL NOT NULL,
  PRIMARY KEY (memory_id, role, entity_id)
);

CREATE TABLE memory_dependencies (     -- derived knowledge that must be re-evaluated when its basis changes
  memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
  depends_on_type TEXT NOT NULL,       -- memory|relationship|segment|entity
  depends_on_id TEXT NOT NULL,
  kind TEXT NOT NULL                   -- inferred_from|summarizes|derived_from
);

CREATE VIRTUAL TABLE memory_vec_v1 USING vec0(
  memory_id TEXT PRIMARY KEY,
  embedding float[768],                -- dimension fixed by the chosen model/MRL size (ADR, P2)
  status TEXT, sensitivity TEXT, kind TEXT    -- metadata columns for filtered KNN
);

CREATE VIRTUAL TABLE memory_fts USING fts5(
  content_norm, content_fold, content_stem, entity_aliases,
  content='', contentless_delete=1,     -- requires SQLite ≥ 3.43; enables real DELETE
  tokenize='unicode61 remove_diacritics 0'
);                                      -- rowid ↔ memories.rowid mapping maintained by the repository

CREATE TABLE open_loops (
  id TEXT PRIMARY KEY, memory_id TEXT REFERENCES memories(id) ON DELETE CASCADE,
  entity_id TEXT, description TEXT NOT NULL,
  due_at TEXT, follow_up_after TEXT NOT NULL, status TEXT NOT NULL,  -- open|done|dismissed|expired
  priority INTEGER NOT NULL DEFAULT 1, times_raised INTEGER NOT NULL DEFAULT 0, last_raised_at TEXT
);

CREATE TABLE inbox_items (             -- Level C confirmations (blocking decisions only)
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,                  -- identity_ambiguity|merge_suggestion|split_suggestion|contradiction|
                                       -- sensitive_confirm|high_impact_confirm|destructive_confirm
  payload_json TEXT NOT NULL, status TEXT NOT NULL,     -- open|resolved|dismissed
  created_at TEXT NOT NULL, asked_inline_at TEXT, times_asked INTEGER NOT NULL DEFAULT 0,
  resolved_at TEXT, resolution_json TEXT, resolution_change_set_id TEXT
);

CREATE TABLE suppressions (            -- prevents re-learning rejected or forgotten knowledge
  id TEXT PRIMARY KEY, subject_id TEXT, predicate TEXT,
  fingerprint TEXT NOT NULL,           -- HMAC(secret, normalized claim) — no plaintext
  reason TEXT NOT NULL,                -- forgotten|rejected
  created_at TEXT NOT NULL
);

CREATE TABLE learning_runs (           -- one per processed segment or document batch
  id TEXT PRIMARY KEY, change_set_id TEXT NOT NULL, source_type TEXT NOT NULL, source_ref TEXT NOT NULL,
  candidates INTEGER, auto_saved INTEGER, provisional INTEGER, pending INTEGER, discarded INTEGER,
  model_id TEXT, prompt_version TEXT, policy_version TEXT, duration_ms INTEGER, created_at TEXT NOT NULL
);
```

Vectors use a **versioned table name** (`memory_vec_v1`). Changing the embedding model creates `memory_vec_v2`, back-fills it in the background, then atomically switches the retrieval config and drops v1.

## 6. Change sets, history and audit

- **Every write happens inside one change set**: an explicit command, a learning run, an import, a review action, a merge or split, a correction, a deletion or a rollback. The change set is the unit of explanation ("bunu neden biliyorsun?"), review and rollback.
- `history` stores per-row versions (before/after JSON) linked to their change set. It is the single undo mechanism for memories, relationships, entities and aliases. Phase 0's separate `memory_history`, `graph_history` and `import_batch_id` mechanisms are replaced by it.
- `audit_log` records security-relevant events (deletions, merges, imports, source authorizations, research queries, policy denials) without personal content. See [SECURITY_MODEL.md §5.10](SECURITY_MODEL.md).
- `decision_json` on each memory and relationship stores *why* the policy chose its level, so the review UI can explain it ("Kendin söyledin · güven 0.90 · düşük risk → otomatik kaydedildi").

## 7. Learning policy (risk-based)

The policy engine (`learning.policy`) is used by every write path except direct user edits, so conversation learning, document learning and inference all follow the same rules.

### 7.1 Inputs to a decision
For each candidate: evidence kind and quote (verified), source trust class (T0–T5), hedging cues, extractor clarity bucket, entity-resolution confidence for every referenced entity, sensitivity tier, predicate or relationship impact, conflict status against existing knowledge, operation type, number of dependents (blast radius) and importance.

### 7.2 Confidence calculation

Confidence estimates **the probability that the stored statement is true as written**. It is computed deterministically. LLM self-assessment is only a bounded input.

```
c_claim = base(evidence_kind) × hedge_factor × clarity_factor
c       = min(c_claim, res(subject), res(object))          # weakest link: who it is about
c       = min(0.99, c + corroboration_bonus)                # independent evidence only, ≤ +0.15
on explicit user confirmation: c = max(c, 0.97)
```

| Evidence kind | base | | Hedge cue | factor |
|---|---|---|---|---|
| Explicit memory command ("bunu hatırla") | 0.95 | | none | 1.00 |
| First-person statement about self ("satranç oynamayı seviyorum") | 0.90 | | mild ("sanırım", "galiba", "herhalde") | 0.75 |
| User's statement about another person ("Ahmet şirket kuruyor") | 0.80 | | strong ("emin değilim", "belki") | 0.60 |
| Reported speech ("Ahmet'in dediğine göre…") | 0.65 | | hypothetical / future | → stored as `plan`, factor 1.0 |
| Implied by context (not stated outright) | 0.55 | | | |
| User-authored personal document (T2) | 0.75 | | **Extractor clarity** | |
| Other local document / third-party text (T1) | 0.40 | | high / medium / low | 1.0 / 0.9 / 0.75 |
| LAZIS inference | 0.45 | | | |

| Entity resolution `res()` | value |
|---|---|
| the user (self) | 1.00 |
| confirmed (by the user) | 0.97 |
| linked (non-name evidence agrees) | 0.90 |
| new entity introduced in the same statement | 0.95 |
| tentative (name-only, single candidate) | 0.70 |
| ambiguous (≥ 2 plausible candidates) | cannot be stored as a fact on an entity → Level C |

**Corroboration** (+0.05 each, max +0.15) counts only **independent** evidence: a different segment at least 6 h apart, or a different source type (conversation vs. user-authored document). Restating within the same segment does not count. LAZIS's own words never count, and **retrieval or repeated use never counts** (§7.6).

The numbers above are initial values. They are calibrated in P9 on the extraction gold set with a reliability diagram, so that each confidence bucket's measured precision matches its label (target: ≥ 95% precision for c ≥ 0.85).

### 7.3 Risk classification

Risk estimates **the harm if the statement is wrong, disclosed or applied**. It is independent of confidence.

| Risk | Any of these conditions |
|---|---|
| **High** | sensitivity = sensitive (unless created by an explicit user command) · operation is a merge, a split or a destructive or bulk change · conflicts with an *active* memory or relationship of medium/high impact · the reference is ambiguous (≥ 2 candidates) · high-impact knowledge (family structure, romantic ties, identity attributes) from a source below T3 (documents, inference) · sensitive information about a third party · blast radius > 20 dependent items |
| **Medium** | sensitivity = personal · high-impact knowledge stated directly by the user (T3+) without conflict · medium-impact knowledge (jobs, locations, social ties, events, projects) · conflicts only with provisional knowledge · the subject is a tentative entity link · blast radius 4–20 |
| **Low** | everything else: normal sensitivity, low impact (hobbies, interests, preferences, skills, plans), resolved subject, no conflict |

Impact comes from the predicate and relationship registries (`impact` field), so it is configuration, not code.

### 7.4 Decision matrix

| Risk \ Confidence | **High** (c ≥ 0.85) | **Medium** (0.60 ≤ c < 0.85) | **Low** (c < 0.60) |
|---|---|---|---|
| **Low** | **A** — automatic | **B** — provisional | B if importance ≥ 0.5, else discard |
| **Medium** | **A** — automatic | **B** — provisional | discard (kept only inside the episode summary) |
| **High** | **C** — confirmation required | **C** | C if importance ≥ 0.7, else discard |

High confidence alone never authorizes a high-risk change: the bottom row is always C.

**Explicit user intent is confirmation.** "Bunu hatırla: annemin tansiyonu var" stores the memory at Level A with `sensitivity=sensitive`. It is never volunteered, only used when relevant. An explicit "Ahmet ile Ahmet Kaya aynı kişi" executes the merge immediately when both targets are unambiguous, with undo. Restricted data is refused regardless of intent.

### 7.5 Level semantics

| Level | Stored status | Used in conversation | Shown to the user | How it changes |
|---|---|---|---|---|
| **A — automatic** | `active` | As established knowledge | In the learning review feed (non-blocking) | Correct/reject/delete via review; superseded by later facts |
| **B — provisional** | `provisional` | Only hedged ("yanılmıyorsam…", "bir ara … demiştin gibi"). Never stated as fact, never in the core profile summary, never the sole basis for a proactive or sensitive follow-up | In the review feed, marked "emin değilim" | Promoted, demoted or archived per §7.6 |
| **C — confirmation** | `pending_confirmation` | **Not used as knowledge.** It may only be used to ask the confirming question | In the Inbox (blocking decision) and optionally asked inline | Resolved by the user only (§9); never auto-applied |

### 7.6 Promotion, demotion and expiry

- **B → A** only through new information: explicit user confirmation ("evet, doğru"), a user approval in the review feed, or independent corroboration that lifts confidence to ≥ 0.85 *and* leaves risk Low or Medium. Each promotion is a change set with reason codes.
- **Retrieval never promotes.** `recall_count` and `last_recalled_at` affect ranking only. LAZIS mentioning a provisional memory and the user not objecting is **not** confirmation. Only an explicit affirmative reply to an explicit question is.
- **Demotion:** user "mark as uncertain" (A → B); a contradicting claim of equal or higher trust (A → `conflict_state=pending`, see §10).
- **Expiry:** provisional memories with no corroboration for 180 days and importance < 0.5 become `archived`. They are excluded from retrieval, still visible and restorable in the Memory view, and never deleted automatically. All durations are configurable.

### 7.7 Policy configuration (`config/learning_policy.yaml`, versioned and hash-stamped)

```yaml
version: 1
thresholds: { high: 0.85, medium: 0.60 }
corroboration: { bonus: 0.05, max_bonus: 0.15, min_gap_hours: 6 }
provisional: { archive_after_days: 180, archive_max_importance: 0.5 }
inline_confirmation: { max_per_reply: 1, defer_in_voice: true, defer_on_emotional_turns: true }
review_mode: calibration            # off | digest | calibration | strict (§12)
calibration_days: 21
overrides:                          # per-category tightening; can only make the policy stricter
  - { match: { category: health }, force_level: C }
```

`overrides` can only tighten the policy (raise a level toward C). Loosening the defaults requires an ADR.

## 8. Memory lifecycle

```mermaid
stateDiagram-v2
    [*] --> Candidate: extracted / imported / explicit / inferred
    Candidate --> Discarded: evidence unverified · restricted · suppressed · low value
    Candidate --> Active: Level A
    Candidate --> Provisional: Level B
    Candidate --> Pending: Level C
    Provisional --> Active: confirmation · approval · independent corroboration
    Provisional --> Retracted: rejected · contradicted by higher trust
    Provisional --> Archived: expiry (§7.6)
    Archived --> Provisional: restored by user
    Pending --> Active: user confirms
    Pending --> Retracted: user rejects
    Pending --> Active: user corrects (new version)
    Active --> Provisional: marked uncertain
    Active --> Superseded: newer fact with change signal
    Active --> Retracted: user rejects / corrects as wrong
    Superseded --> Active: rollback
    Retracted --> Active: rollback
    Active --> [*]: hard delete (forget)
    Provisional --> [*]: hard delete
```

`Discarded` candidates are not stored. They appear only as counts in `learning_runs`, so recall can be measured without retaining unwanted content.

## 9. Confirmation workflow (Level C)

1. The policy creates an `inbox_items` row, and the candidate is stored as `pending_confirmation`.
2. **Inline asking** (natural, optional): at most one confirmation question per reply, placed at the end, and only when the conversation is not emotionally loaded. In voice mode, it is deferred unless the answer depends on it. Example: *"Bu arada, bahsettiğin Ahmet çocukluk arkadaşın olan Ahmet mi?"*
3. **Inbox** (UI): every open item with context, the source quote and one-click options (confirm / correct / reject / "farklı kişiler" / later).
4. **Resolution** creates a change set (`kind=review_action`). Confirmation adds `user_confirmation` evidence (T5). Rejection retracts and adds a suppression fingerprint, so it is not re-learned.
5. **Reminders:** an unresolved item may be re-asked inline at most once more, after ≥ 7 days and only when topically relevant. Otherwise it waits in the Inbox. **Pending items are never auto-applied and never silently expire into facts.**

## 10. Contradiction resolution

When a new candidate *C* conflicts with existing knowledge *M* (same subject + single-cardinality predicate, or a relationship type with single cardinality):

```mermaid
flowchart TD
    A[Candidate C vs existing M] --> B{Same value?}
    B -- yes --> D[Duplicate: add evidence to M<br/>corroboration if independent]
    B -- no --> C{Predicate cardinality}
    C -- multi --> E{Near-duplicate?<br/>cos ≥ 0.92, same entities}
    E -- yes --> D
    E -- no --> F[Coexist: C goes through the policy as new knowledge]
    C -- single --> G{Explicit change signal?<br/>'taşındım', 'artık', 'ayrıldık', newer valid_from}
    G -- yes --> H{risk of C}
    H -- low/medium --> S[Supersede: M.valid_to = C.valid_from<br/>M → superseded, C → active]
    H -- high --> Q[Level C: confirm the change]
    G -- no --> I{M status}
    I -- provisional --> J{trust C ≥ trust M?}
    J -- yes --> R[Retract M, C through policy]
    J -- no --> K[Keep M, C → provisional + conflict link]
    I -- active --> L[M.conflict_state = pending<br/>C → pending_confirmation<br/>'Daha önce İzmir demiştin, değişti mi?']
```

- While `conflict_state = pending`, M is still used, but rendered with a staleness hedge ("(güncel olmayabilir)").
- Superseded knowledge stays queryable for history ("Eskiden nerede yaşıyordum?") and is excluded from present-tense retrieval.
- **Trust order** for tie-breaks: T5 user edit/confirmation > T4 explicit command/bootstrap > T3 conversation statement > T2 user-authored document > T1 other documents/inference. T0 research never participates: it can only trigger a question.

## 11. User corrections and propagation

Corrections must fix what was wrong **without destroying unrelated knowledge**. The precision comes from mention-level grounding (`memory_entity_links.mention_id`, `evidence.mention_id`).

| Correction | Example | Propagation |
|---|---|---|
| Fact value | "Hayır, Ayşe öğretmen değil, hemşire." | New version of the memory (`origin=user_edit`, T5). Dependents in `memory_dependencies` are marked for re-evaluation. The profile summary is invalidated. The old value gets a suppression fingerprint (`reason=rejected`) |
| Identity (wrong person) | "O dediğim Ahmet iş yerindeki Ahmet'ti." | Only the mention(s) the user refers to are reassigned. Memories and relationships **grounded by those mentions** move to the correct entity. Knowledge grounded by other mentions is untouched. One change set (`kind=correction`); a distinction constraint is suggested |
| Relationship type | "Mehmet onun kardeşi değil, kuzeni." | The relationship gets a new version with type changed. Path-derived answers are recomputed on demand, since nothing derived is stored |
| Temporal | "Oraya 2023'te taşınmıştım, 2024'te değil." | `valid_from` is updated. Superseded neighbors' `valid_to` is adjusted in the same change set |
| "Bu yanlış, unut" | — | Retract + suppression, or a hard delete if the user says "sil" (§17) |

**Inferred knowledge** (`origin=inferred`) records its basis in `memory_dependencies`. If any basis is corrected, retracted or deleted, the inferred item is re-evaluated: retracted if its basis is gone, kept provisional otherwise.

## 12. Learning review mode

Review is a **window onto autonomous learning, not a gate in front of it.** LAZIS uses Level A knowledge immediately in every mode except `strict`.

| Mode | Behavior | Intended use |
|---|---|---|
| `calibration` *(default for the first 21 days)* | Every new A and B item appears prominently in the "Öğrendiklerim" feed, with a daily count badge. Non-blocking | Build trust and tune the policy early on |
| `digest` *(default afterwards)* | A daily or weekly summary card of what was learned; the full feed stays available | Normal long-term use |
| `off` | No prompts. Items stay browsable in the Memory view | Users who do not want to review |
| `strict` | Everything that would be A is stored as B until reviewed. Opt-in only | Maximum control; it reduces autonomy deliberately |

**Review actions** (each creates a change set):

| Action | Effect |
|---|---|
| **Approve** | `review_state=approved`, and user-confirmation evidence is added. A provisional item is promoted to A if risk ≤ Medium |
| **Correct** | Edit inline (value, person, relationship, dates, sensitivity), then propagation per §11 |
| **Reject** | `status=retracted`, plus a suppression fingerprint so it is not re-learned |
| **Delete** | Hard delete per §17 (with optional evidence redaction) |
| **Mark uncertain** | A → B (provisional) |
| **View source** | Evidence quotes, a jump to the message or document, and the policy decision ("neden?") |
| **View related entities** | The entities and relationships the item links to, with their own status |

The feed is filterable by level, entity, source (conversation/document/import), sensitivity and date. Bulk actions apply to one learning run (e.g., "bu konuşmadan öğrendiklerinin hepsini geri al").

## 13. Rollback behavior

| Scope | Mechanism |
|---|---|
| One memory or relationship | Revert to a chosen version from `history` |
| One change set (learning run, import, merge, split, correction, bulk review) | Replay its `history` rows in reverse order |
| Conflicting later changes | If a row's current version is not the version that change set produced, it is a **conflict**. Conflicts are listed for the user (keep current / revert anyway). Newer user edits are never clobbered silently |
| Rollback of a rollback | Allowed: a rollback is itself a change set (`kind=rollback`, `reverts_change_set_id`) |
| Learning-run rollback | Offers "bunları tekrar öğrenme" (add suppressions, default on) |
| Last resort | Restore a pre-change snapshot (imports and migrations always take one), with a warning that later changes are lost |

## 14. Write paths summary

| Path | Trust class | Default handling |
|---|---|---|
| Explicit command | T4 | Policy with explicit intent: usually A; sensitive allowed and flagged; restricted refused |
| Conversation statement (extracted) | T3 | Full policy (§7.4) |
| Bootstrap import | T4 | Preview is the confirmation: accepted items → A ([KG design §9](KNOWLEDGE_GRAPH_DESIGN.md)) |
| User edit / review approval / confirmation | T5 | A |
| User-authored personal document | T2 | Full policy; the source class caps high-impact social facts at C ([LOCAL_INGESTION_ARCHITECTURE.md](LOCAL_INGESTION_ARCHITECTURE.md)) |
| Other documents, third-party text pasted by the user | T1 | Never personal facts about the user automatically; project/reference domain at most B; personal claims → C |
| LAZIS inference | T1 | At most B; never A without confirmation |
| Research | T0 | Never stored as memory. Promotion only by explicit user action (then T5 confirmation + research URL evidence) |

### 14.1 Explicit memory commands (Turkish)

Detection is a **two-stage router**. Stage 1 uses a deterministic lexicon with suffix tolerance (`config/lexicons/memory_commands.tr.yaml`). Stage 2 is an LLM tool call that extracts parameters.

| Intent | Example triggers | Tool |
|---|---|---|
| remember | "bunu hatırla", "aklında tut", "unutma ki", "not al", "kaydet şunu" | `memory.remember(content, about?)` |
| forget | "bunu unut", "bunu sil", "X'i hatırlama", "bunu kaydetme" | `memory.forget(target_query, scope)` |
| recall | "benim hakkımda ne biliyorsun?", "Ayşe hakkında ne hatırlıyorsun?", "ne zaman söylemiştim?" | `memory.search(query, entity?)` |
| correct | "yanlış hatırlıyorsun", "aslında …", "düzelt: …" | `memory.correct(target, new_content)` |
| off-record | "bu kayıt dışı", "bunu öğrenme" | sets segment `off_record = true` |

Forget **always confirms the target** when more than one item matches ("Şu üç notu buldum, hangisini sileyim?"). That is a destructive operation with an ambiguous target, so it is Level C. Single-match forgets execute immediately, with an undo hint.

## 15. Turkish-aware text processing (`lazis.text`)

| Problem | Example | Handling |
|---|---|---|
| Turkish casing | `İ`/`i`, `I`/`ı`; Python `str.lower()` maps `I`→`i` (wrong) | Locale-aware `tr_casefold()` |
| Missing diacritics in typing | "sirketteki toplanti" | `content_fold`: ç→c, ğ→g, ı→i, ö→o, ş→s, ü→u; queries are searched in both forms |
| Agglutination | "toplantılarımızdan" | Snowball Turkish stemmer (PyStemmer) → `content_stem` |
| Proper-noun suffixes | "Ahmet'e", "Ahmet'in", "Ahmetle", "Ahmetin" | Apostrophe split; without an apostrophe, alias prefix plus a suffix whitelist (vowel-harmony aware) |
| Kinship and possessives | "annem", "eşimin annesi", "abimin kızı", "çocukluk arkadaşımın kardeşi" | Kinship + qualified-role lexicons and a possessive chain parser ([KG design §4](KNOWLEDGE_GRAPH_DESIGN.md)) |
| Hedging cues | "sanırım", "galiba", "emin değilim" | Hedge lexicon → `hedge_factor` (§7.2) |
| Numbers and dates | "geçen salı", "iki hafta sonra", "Ramazan Bayramı'nda" | Relative date resolver anchored to message time (Europe/Istanbul) plus a religious/national holiday table (config, yearly) |

Property-based tests (hypothesis) cover round-trip invariants (`fold(norm(x)) == fold(x)`) and known tricky pairs.

## 16. Learning pipeline (conversation segments)

### 16.1 Segmentation
A segment closes when one of these happens: the user is idle for more than 3 min (configurable), the conversation ends or the app goes to the background, 30 turns accumulate, or a topic shift is detected (embedding drift over a 3-turn window). Off-record segments are never processed.

### 16.2 Durable jobs (`jobs` table, P1)
`id, type, payload_json, priority, status (queued|running|retry|done|failed|dead), attempts, run_after, locked_at, last_error, created_at`. The queue is crash-safe (state in SQLite), retries with exponential backoff, and dead-letters after 5 attempts with a System-view notice.

### 16.3 Idle-aware scheduler and preemption
- Background LLM work starts only if the assistant state is IDLE, no voice session is active, and the last user activity was ≥ 10 s ago.
- When a foreground turn starts, the in-flight background request is cancelled (stream closed), the job is set to `retry`, and the foreground request proceeds. This is what keeps background jobs from blocking the user, whatever the slot configuration.
- Background calls are small (one segment per call), so preemption wastes little work. They use the **same `num_ctx`** as foreground calls, so they never trigger a model reload ([TECHNOLOGY_DECISIONS.md §2.2](TECHNOLOGY_DECISIONS.md)).
- **Cache protection:** a background request can evict the conversation's cached prefix when the engine has a single slot. Two mitigations exist: a second slot (`OLLAMA_NUM_PARALLEL=2`), or re-warming the active conversation's prefix during idle after background work. The choice is made by benchmark B3e ([BENCHMARK_PLAN.md §6](BENCHMARK_PLAN.md)).

### 16.4 Stages

| # | Stage | Implementation | Output |
|---|---|---|---|
| 1 | Extract | LLM call with JSON-schema output (`think=false` by default); Turkish prompt with guidelines and few-shot examples; input = segment messages with IDs | typed candidates with `evidence: {message_id, quote}`, hedge cues, clarity bucket |
| 2 | Verify evidence | Code: the quote must occur in the referenced **user** message (normalized match, ≥ 0.9 fuzzy). LAZIS's own words are never evidence about the user | hallucinated claims dropped |
| 3 | Normalize | predicate/relationship mapping, value normalization, dates resolved relative to message time, plans separated from facts | normalized candidates |
| 4 | Restricted-data check | detectors (TC Kimlik No with checksum, IBAN TR mod-97, card numbers with Luhn, password/OTP patterns) | drop + metric (never stored) |
| 5 | Resolve entities | `graph.EntityResolver` (mention-level, [KG design §6](KNOWLEDGE_GRAPH_DESIGN.md)) | entity IDs + `res()` values, or ambiguity |
| 6 | Suppression check | HMAC fingerprint vs. `suppressions` | drop if forgotten or rejected |
| 7 | Dedupe + contradiction | §10 | action per candidate |
| 8 | Sensitivity + risk | category classifier (rules + extractor label) → tier; risk factors (§7.3) | risk level |
| 9 | Confidence + level | §7.2 and §7.4 | A / B / C / discard, with `decision_json` |
| 10 | Persist | one transaction per learning run: memories/relationships + evidence + links + history + change set (+ inbox items, open loops) | rows |
| 11 | Index | FTS rows in the same transaction; vectors written immediately after (idempotent, reconciled at startup) | indexed |
| 12 | Episode | short episode summary for the segment (`kind=episode`, depends on the segment) | episodic memory |
| 13 | Follow-ups | dated plans and events → `open_loops` | follow-up candidates |

Extraction quality is measured continuously on the gold set ([TESTING_STRATEGY.md](TESTING_STRATEGY.md)). Prompt, policy and config versions are stamped on every record, so regressions can be traced and runs selectively re-processed.

## 17. Deletion semantics ("unutma hakkı")

| Scope | Effect |
|---|---|
| Single memory | Delete the row, its vectors, FTS rows, evidence and links. History rows are reduced to content-free tombstones. A suppression fingerprint (`reason=forgotten`) is added. Dependents are re-evaluated; the profile summary and episodes citing it are regenerated |
| Evidence redaction (offered, default **ask**) | Replace the quoted spans in `messages.content` with `[silindi]`, so the fact cannot be re-extracted or seen in history |
| Per person ("Ahmet hakkında her şeyi unut") | Cascade over memories linked to the entity, its relationships, aliases, mentions and the entity itself. Inbox items are purged. One confirmation dialog shows the counts (Level C: destructive, bulk) |
| Conversation | Delete messages, segments and episodes. Knowledge whose **only** evidence was this conversation is listed for the user to keep or delete |
| Source (document folder) | See [LOCAL_INGESTION_ARCHITECTURE.md §6](LOCAL_INGESTION_ARCHITECTURE.md) |
| Everything | Secure wipe: close DBs, delete files, delete the Keychain key (encrypted data becomes unrecoverable) and backups (explicit second confirmation) |

**Backups:** deleted data persists in older encrypted snapshots until rotation. The UI says this plainly and offers "purge from backups" (re-create backups from the current state). `PRAGMA secure_delete=ON` zeroes freed pages in the live database.

## 18. Retrieval

### 18.1 Pipeline (per turn)

```mermaid
flowchart LR
    Q[User message + last 2 turns] --> L[Entity linking<br/>alias index + kinship/role parser]
    Q --> EQ[Query embedding]
    L --> EC[Entity-centric fetch:<br/>facts of linked entities<br/>+ 1–2 hop relationships]
    L --> PQ[Relational path query<br/>e.g. 'çocukluk arkadaşımın kardeşi']
    EQ --> VK[Vector KNN top-30<br/>status ∈ active, provisional]
    Q --> FT[FTS5 BM25 top-30<br/>norm + fold + stem columns]
    EC --> F[Fusion: RRF]
    PQ --> F
    VK --> F
    FT --> F
    F --> S[Score = rrf × importance × confidence × recency × context_fit]
    S --> G[Policy gates: sensitivity, status rendering,<br/>already-in-context dedupe]
    G --> M[MMR diversity + token-budget packing]
    M --> OUT[MemoryContext:<br/>items with status markers + open loops due]
```

- **Always in the stable prefix:** a compact user core profile (≤ 300 tokens; **active knowledge only**; regenerated on change, applied at the next compaction or session).
- **Status rendering:** `active` items are plain facts. `provisional` items carry a hedge marker, and the model is instructed never to state them as certain. Items with `conflict_state=pending` carry a staleness marker. `pending_confirmation`, `archived`, `superseded` and `retracted` items are **excluded** from present-tense context.
- **Sensitivity gating:** `sensitive` items are included only when the turn is about the same topic or entity. They are never volunteered in unrelated conversation.
- **Already-in-context dedupe:** memories already injected earlier in the same session are referenced by a short ID rather than repeated. This keeps the append-only context compact ([ARCHITECTURE.md §6](ARCHITECTURE.md)).
- **Relational answers:** path queries return the path with each edge's status, so the answer carries the weakest link's certainty ([KG design §6.5](KNOWLEDGE_GRAPH_DESIGN.md)).
- **Temporal rendering:** items carry time context ("(2024'ten beri)", "(eskiden)").
- **Budgets:** text ≤ 1,200 tokens; voice ≤ 500 tokens.
- **Recall bookkeeping:** `recall_count`/`last_recalled_at` are updated asynchronously and affect ranking only.

### 18.2 No-fabrication contract
The model may claim to remember something ("demiştin", "bahsetmiştin", "hatırladığım kadarıyla") **only** if a retrieved item supports it. A post-generation **memory-claim guard** ([PERSONALITY_ENGINE.md §8](PERSONALITY_ENGINE.md)) checks memory-claim phrases against the turn's MemoryContext and regenerates unsupported claims. When nothing is retrieved, the persona instructs the model to say it does not know ("Bunu bana söylediğini hatırlamıyorum").

### 18.3 Performance targets *(unmeasured)*
Entity linking ≤ 5 ms · query embedding ≤ 25 ms (warm) · KNN over 50k × 768 float32 ≤ 30 ms (plaintext; the encrypted case is measured in SPK-05) · FTS ≤ 10 ms · total ≤ 80 ms p95. Verified by a perf test with a synthetic 50k-memory database, both plain and SQLCipher-encrypted.

## 19. Backup and recovery

- **Snapshot mechanism:** `sqlcipher_export()` into an encrypted backup file (or `VACUUM INTO` in unencrypted test setups) produces a consistent copy without stopping the app.
- **Schedule:** daily at the first idle moment; before every migration; before every import apply and source re-index; on demand.
- **Retention (configurable):** 7 daily, 4 weekly, 6 monthly.
- **Integrity:** `PRAGMA integrity_check` on the snapshot, plus a SHA-256 manifest recording the key version.
- **Restore:** stop core, verify the snapshot, swap files, run migrations forward, restart. A restore round-trip test runs in CI. Key handling is in [SECURITY_MODEL.md §5.1](SECURITY_MODEL.md).
- **Portable export:** JSON export of memories, graph and settings (human-readable; for the user's own archive).
- **WAL:** `journal_mode=WAL`, `synchronous=NORMAL` (FULL during migrations), `foreign_keys=ON`, `busy_timeout=5000`, `temp_store=MEMORY`.

## 20. Memory API surface (internal)

```python
class MemoryService(Protocol):
    async def remember(self, cmd: RememberCommand, ctx: TurnContext) -> WriteResult: ...
    async def forget(self, target: ForgetTarget, ctx: TurnContext) -> ForgetResult: ...
    async def correct(self, target: KnowledgeRef, new: ClaimDraft, ctx: TurnContext) -> WriteResult: ...
    async def get(self, id: MemoryId) -> Memory | None: ...
    async def search(self, q: MemoryQuery) -> Page[Memory]: ...             # UI browsing
    async def history(self, id: MemoryId) -> list[Version]: ...
    async def revert(self, id: MemoryId, version: int) -> WriteResult: ...

class LearningPolicy(Protocol):                                             # learning.policy
    def decide(self, cand: Candidate, ctx: PolicyContext) -> Decision: ...  # pure, deterministic, versioned

class ReviewService(Protocol):
    async def feed(self, f: ReviewFilter) -> Page[ReviewItem]: ...
    async def act(self, item: KnowledgeRef, action: ReviewAction, payload: dict | None) -> WriteResult: ...

class ChangeSetService(Protocol):
    async def revert(self, change_set_id: str, conflict_choices: dict[str, str] | None) -> RevertResult: ...

class RetrievalService(Protocol):
    async def retrieve(self, q: RetrievalQuery) -> MemoryContext: ...       # per turn, budgeted
```

All writes go through one **unit of work** bound to one change set. Knowledge rows, evidence, links, history and FTS rows commit atomically. Vector writes follow immediately and are idempotent; a startup reconciler repairs any gap. `LearningPolicy.decide` is a pure function of its inputs plus the versioned policy file, so every decision is reproducible and unit-testable.

## 21. Open questions (tracked)
- Length of the calibration period (default 21 days) and the default afterwards (`digest`): **user decision** ([PHASE_0_FINAL_REVIEW.md §N](PHASE_0_FINAL_REVIEW.md)).
- Should health information about third parties ever be learned automatically at Level B, or always C? Default: always C (`overrides`).
- Episode summaries: per segment (default) or a daily journal roll-up too? Proposed: daily roll-ups in P10.
