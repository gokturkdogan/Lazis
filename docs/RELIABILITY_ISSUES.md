# Reliability issues

Open faults in what LAZIS stores or says, recorded apart from the phase reports. An entry stays open until a fix is measured on real Gemma and the owner accepts it. Entries are not closed by performance work.

## REL-001: an uncertain statement about a person is stored as a certain plan

| | |
|---|---|
| **Status** | Open |
| **Severity** | Reliability fault (owner's classification, 2026-11-03) |
| **Must be handled** | Before moving to the real user profile |
| **Found in** | Compaction latency baseline, code `298ad54` (product code as `c366fbf`), synthetic data in throwaway profiles |

**What the user said:** "İş arkadaşım Mehmet de galiba 10 Kasım'da İzmir'e gidecek, henüz kesin değil."

**What should be kept:** the trip is a possibility and not settled.

**What was stored** (active memory, origin `stated`, all nine baseline runs):

| Run | Predicate / value | Content | Uncertainty kept |
|---|---|---|---|
| gap 30, run 1 | `note` / İzmir | Mehmet 10 Kasım'da İzmir'e gidecek. | **No** |
| gap 30, run 2 | `plan` / Mehmet de galiba 10 Kasım'da İzmir'e gidecek | Mehmet 10 Kasım'da İzmir'e gidecek. | **No** in the content |
| gap 60, run 1 | `note` / İzmir | Mehmet 10 Kasım'da İzmir'e gidecek. | **No** |
| gap 60, run 2 | `note` / İzmir | Mehmet'in 10 Kasım'da İzmir'e gideceği söyleniyor. | Partly |
| gap 6, run 1 | `plan` / Mehmet de galiba 10 Kasım'da İzmir'e gidecek | Mehmet'in 10 Kasım'da İzmir'e gitme ihtimali bulunuyor. | Yes |
| gap 6, run 2 | `plan` / Mehmet de galiba 10 Kasım'da İzmir'e gidecek | Mehmet'in 10 Kasım'da İzmir'e gideceği tahmin ediliyor. | Yes |
| gap 6, run 3 | `plan` / Mehmet de galiba 10 Kasım'da İzmir'e gidecek | Mehmet'in 10 Kasım'da İzmir'e gideceği tahmin ediliyor. | Yes |
| gap 30, emptier system | `note` / İzmir | Mehmet 10 Kasım'da İzmir'e gidecek. | **No** |
| gap 60, emptier system | `plan` | Mehmet 10 Kasım'da İzmir'e gidecek. | **No** |

The uncertainty is lost outright in five of nine runs. Memory jobs were still running when the gap 6 run 1 and run 2 reports were written, so those two memory lists may be incomplete; in gap 6 run 3 all jobs finished. The gap 30 run 3 was stopped on critical memory pressure after 17 turns; it wrote no report and is not counted.

**Later run (limit 8, 40 messages, 60 s, 2026-11-04):** stored again as certain, `plan`: "Mehmet 10 Kasım'da İzmir'e gidecek." Six of ten runs now. Summary and answer kept the uncertainty.

**Where it does not appear:** the active summary keeps the uncertainty in the seven runs where it still mentions Mehmet. In gap 6 runs 2 and 3 the summary has no Mehmet line; that is a separate fault, [REL-002](#rel-002-a-stored-fact-about-a-person-cannot-be-recalled).

**Related, not the same fault:** in gap 30, runs 1 and 2, the reply to the same message speaks of Mehmet "taşınma" (moving house), which the user did not say.

**Cause:** not investigated. The record is written by the memory learning step; the step or rule responsible has not been identified.

**How this is judged (owner's decision, 2026-11-03):**
- Memory learning rules do not change during the compaction latency work.
- Performance acceptance judges new memory or fact errors caused by changes A, B or C, separately from faults already in the system. This fault is measured in the baseline and is not attributed to them.
- This does not close the fault. It stays open in the general reliability reporting.

**Evidence:** `evals/reports/phase10/perf/baseline_cache2048_gap*_r*.json`, fields `memories`, `summaries`, `turns`.

## REL-002: a stored fact about a person cannot be recalled

| | |
|---|---|
| **Status** | Open |
| **Kind** | Recall failure. Not the same as REL-001, where a fact is recalled with its uncertainty lost |
| **Found in** | Compaction latency baseline, gap 6 runs 2 and 3, code `298ad54` and `75bec72` (same product code), synthetic data in throwaway profiles |

**What the user said (message #7):** "İş arkadaşım Mehmet de galiba 10 Kasım'da İzmir'e gidecek, henüz kesin değil."

**What the user asked (turn 33):** "Mehmet ne zaman nereye gidiyordu? Kısaca yaz."

**What was answered:**
- gap 6, run 2: "Kayıtlarımda Mehmet isimli birine dair herhangi bir gitme veya seyahat bilgisi bulunmuyor efendim."
- gap 6, run 3: "Mehmet ile ilgili böyle bir bilgi bulunmuyor efendim."

**What the runs show:**
- The first summary (v1) carries the Mehmet line in both runs. The second (v2) no longer does, and neither do later versions.
- Every one of those summaries reports `dropped: 0`, while `kept` falls (run 2: 18 → 16; run 3: 20 → 14). The loss is not reported as a drop.
- At the end of both runs an active memory about Mehmet's trip exists. The reports do not show whether it existed by turn 33 or whether recall offered it to the model.
- The original message stays stored in full: history coverage has no gap and nothing was trimmed.
- In the other seven runs the active summary at turn 33 holds the line and the answer gives the trip.

**What the quality score covers:** the 126/128 measure scores **one compaction only**. It does not cover a summary being rewritten, which is where this loss appears, so 126/128 says nothing about fact retention over several compaction cycles. Before A, B or C can be accepted, retention must be measured over several cycles: see [COMPACTION_MULTI_CYCLE_QUALITY_TEST.md](COMPACTION_MULTI_CYCLE_QUALITY_TEST.md).

**Cause:** not investigated. Neither the rewrite nor recall has been identified as responsible. Seen only at the 6 s gap so far (2 of 3 runs there, 0 of 6 at other gaps): too few to call it specific to that gap.

**Related, not the same fault:** in 2 of 9 runs (gap 6 run 2, gap 60 emptier system) the question about choosing a restaurant is answered without the wife's vegetarian diet. In the gap 60 run the summary and a memory both hold the fact, so this is the reply not using it. Not investigated.

**Relation to [REL-003](#rel-003-facts-disappear-silently-when-a-summary-is-rewritten):** the summary side of this fault is the silent rewrite loss recorded there: here too the Mehmet line leaves between v1 and v2 with `dropped: 0`. REL-003 does not fully explain this fault, because a memory about the trip also existed by the end of both runs and recall at turn 33 was not recorded. The multi-cycle test did not reproduce this Mehmet case. Each entry stays open until its own fix is measured.

**How this is judged:** no summary or memory rule changes during the compaction latency work. It is a baseline fault, and performance acceptance judges new errors caused by changes A, B or C separately from it. The summary prompt stays unchanged. The fault stays open in the general reliability reporting.

**Evidence:** `evals/reports/phase10/perf/baseline_cache2048_gap6_r2.json` and `..._gap6_r3.json`, fields `turns[32]`, `summaries`, `memories`.

**Phase 15C (2026-11-07), recall checked without a model:** the active memories stored at the end of both failing runs were rebuilt in a test database: 9 for run 2, 6 for run 3. The turn-33 question "Mehmet ne zaman nereye gidiyordu? Kısaca yaz." was then run through `retrieval.recall` with the product's default budget (200 tokens, 440 characters). The Mehmet trip is in the memory block in both. So did three other phrasings, with the Mehmet memory alone. With the final memory state, recall does not lose the fact. That leaves two explanations a model-free check cannot decide: the memory did not exist yet at turn 33 (the old automatic learning ran in the background), or the reply did not use it (or trusted the summary, REL-003). No concrete code fault was found, so nothing was changed and the fault stays open. With automatic learning off, a stated fact like this one no longer becomes a memory at all; it lives only in the conversation and its summary.

## REL-003: facts disappear silently when a summary is rewritten

| | |
|---|---|
| **Status** | Open |
| **Priority** | **Priority technical debt** (owner's decision, 2026-11-04) |
| **Kind** | Silent data loss in the active summary. The original messages and earlier summary versions stay stored |
| **Fix** | None started. The summary prompt, learning rules and memory architecture stay unchanged until the owner decides otherwise |
| **Found in** | Multi-cycle test, 2026-11-04, code `703941c` (product code as `c366fbf`), 10 conversations, five summary versions, learning off, synthetic data in throwaway profiles |

**Relation to REL-002:** REL-002 is what the user sees: told there is no such information about a stored fact. REL-003 is one mechanism behind it, measured on its own: a rewrite leaves a fact out and reports nothing. Fixing one does not close the other. REL-002 also involves recall, which this test does not cover.

| Summary version | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Facts kept of 64 (word check) | 62 | 61 | 59 | 59 | 56 |
| Conversations with a silent loss | 0 | 1 | 3 | 3 | 4 |

- Six facts were lost at a rewrite: `vejetaryen`, `cuma`, `8 bin`, `Kaş`, `Mavi Koy`, `35 bin`. Every one reports `dropped: 0`. `Kuzey` and `15 Aralık` are the two already missing from the 126/128 measure. **Corrected 2026-11-04:** they were not simply absent; in D2 seed 11 the model wrote the item, with its quote from LAZIS's message, and the evidence check refused it (`dropped: 1`).
- No interruptions, no user traffic and no memory pressure in this test, so the loss needs none of them.
- Seed 7 lost 1 fact, seed 11 lost 7. Two seeds show large effects only.
- **The word check undercounts.** Read by hand: "Kaş'a otobüsle" left with the same rewrite in D5 seed 11, and "Ayşe: kız kardeşi" left at version 3 in D1 in both seeds while the word `Ayşe` stayed. So the real figure is worse than 56 of 64. The 50 summaries have not all been scored claim by claim.

**Why the audit does not see it:**

1. **It measures something else.** `dropped_items` counts items in the model's *new output* that fail the evidence check (`verify_items`, `compaction.py`). A fact the model does not write is never an input. It guards against invention, not loss.
2. **Nothing compares versions.** The previous summary goes to the model only as text with the request to keep valid items (rule 9, `prompts.py`). No code checks that they were kept.
3. **`kept_items` is a net count of the newest version.** It can rise while a fact is gone: filler items replace it (D5 seed 7: 8 → 16 at version 4 with `vejetaryen` still missing).
4. **Two more paths lose text uncounted.** `parse_summary` keeps only the complete items of output cut at the token limit, with no count or log. `_str` cuts an item's text at 300 characters; this is visible in the data ("Düzenl" in D5 seed 7).
5. **A passing item can still change meaning.** The check compares `quote` with the source. It does not compare `text` or `certain` with `quote`. "Araba kiralama: True (Eski: user reddetti, Yeni: assistant önerisi)" passed in D5 seed 7. This is also how an uncertain fact could be made certain; the summaries here did not show that happening.

**Cause, measured from raw output (limit 8 multi-cycle run, 2026-11-04, [MULTI_CYCLE_LIMIT8_REPORT.md](MULTI_CYCLE_LIMIT8_REPORT.md)):** the 50 summaries were byte-identical to the limit 32 run, so the checkpoint limit is not involved. Two mechanisms:
- **A, omission with room left (the main one):** five of the six facts lost by the word check left in complete outputs of 593–739 tokens. A higher output limit does not help.
- **B, cut at the output limit:** 16 of 50 outputs stopped at 1200 tokens (`done_reason: length`) and were salvaged silently. Sections are written in schema order, with open questions before constraints, people and instructions; of those 16, 12 never reached instructions, 9 people, 8 constraints. "Ayşe: kız kardeşi" left this way.

- **C, refused by the evidence check:** a true item whose quote comes from the wrong message. Seen once (`Kuzey`, `15 Aralık`). No fix is proposed: the check keeps LAZIS's words from becoming the user's.

**Observable since 2026-11-04 ([REL003_OBSERVABILITY_REPORT.md](REL003_OBSERVABILITY_REPORT.md)):** `summary.output`, `summary.rewrite`, `engine.summary_audit`, and a 20-claim set that gives no general loss rate. The summary itself is unchanged. Planned, not approved: [REL003_FIX_PLAN.md](REL003_FIX_PLAN.md).

**Fix 3 (write decisions and instructions first), `3f6f260`, short trial 2026-11-04 ([REL003_FIX3_REPORT.md](REL003_FIX3_REPORT.md)):** cut outputs 4 of 12 → 0 of 12, and `kız kardeş`, `8 bin`, `vejetaryen` came back in these chosen conversations. New: facts are written under "Kullanıcının talimatları", which the word check and the claim set do not see. Facts arriving after the first summary are untested. Not accepted yet; the full test has not run.

**Fix 3 with a definition of `instructions`, `df4da97`, same short trial:** no facts under instructions and no cuts, but D5 seed 7 lost `vejetaryen` from the first summary ("Beslenme Tercihleri [#8]") and `Mavi Koy` at version 3. Twelve summaries cannot tell the rule from natural variation. A synthetic check kept three of four real instructions and lost a request to be reminded. **New fault, not caused by this change:** "5 Nisan" became "05.04.2024", an invented year, passing because `text` is not checked against `quote`. Not accepted.

**Facts arriving after the first summary (2026-11-04, [LATE_FACTS_AND_ARCHITECTURE_REVIEW.md](LATE_FACTS_AND_ARCHITECTURE_REVIEW.md)):** new facts mostly enter, and old values did not read as current. But a settled plan, a cancellation and a preference were lost in one seed, a current decision was refused after the model rewrote its verified quote, and a reminder became a goal. 14 of 20 missing words were still in verified quotes, which are not shown in later turns. The answers then told the user they had said no such thing. **Separate gap, not this fault:** LAZIS can say it will remind, and there is no reminder feature.

**Status of Fix 3 (owner's decision, 2026-11-04): experimental, not complete.** The section order and `instructions` rule (`s3-v5`) are not accepted. They live on branch `experiment/rel003-s3-v5`, and `main` is back on `s3-v3`: [S3_V5_ISOLATION_PLAN.md](S3_V5_ISOLATION_PLAN.md). Commits `3f6f260` and `df4da97` stay in `main`'s history, undone by a later commit.

**Model-free design replay (2026-11-04, [SAFE_CARRY_DESIGN.md](SAFE_CARRY_DESIGN.md)):** 88 stored outputs, each reproduced byte for byte. Carrying verified user items in code, shown as the user's own sentence, with a code check for changes: current facts lost 70 → 0, uncertain facts lost 6 → 0, no claim worse than today, in rendered text only. Carrying alone raised stale values from 0 to 18. On hand-written hard cases the change check missed 4 of 17 real changes and raised 3 false alarms on 6 unrelated pairs. Nothing here shows how Gemma would answer: that needs a model run.

**Earlier reading, before raw output was kept:** Cause of the omission itself: not established.** Evidence against truncation as the main cause, not proof: three of the four loss events took 38–44 s, well under the 60–64 s plateau, and every lost line was in the first two sections, while a cut would remove the last ones if output follows the schema order. Raw model output is not stored, so this cannot be settled from these reports. Whether the filler crowds out facts is unknown; see below.

**Replaying other detectors over the stored summaries** (`evals/runners/p10p_loss_audit_replay.py`, results `evals/reports/phase10/perf/cycles/loss_audit_replay.json`; no model; chosen after the losses were known, on the same data, so these figures do not predict other data):

| Detector | Loss events seen (of 4) | Pairs flagged (of 40) | Note |
|---|---|---|---|
| `dropped_items` > 0 | 0 | 0 | |
| `kept_items` fell | 4 | 17 | Mostly no real fact behind it |
| A dialogue message is no longer cited | 3 | 4 | 4 of 6 facts. Misses a fact whose message is still cited for something else (`vejetaryen` #8, `35 bin` #6). The fourth flag is a real unscored line. Also flags `#7` in exactly the two REL-002 runs (3 flags in 25 long-run pairs) |
| A previous line has words found nowhere in the new text | 4 | 10 | Besides the 4: `kız kardeşi` twice (word check missed it), a breakfast line twice, rewording twice. Noisy on the long runs (10 of 25 pairs; those read were mostly merged lines). Candidates to read, not a verdict |

**New evidence on varied text, no repeated filler (limit 8 run, 40 messages, 60 s, 2026-11-04, [LONG_CONVERSATION_LIMIT8_REPORT.md](LONG_CONVERSATION_LIMIT8_REPORT.md)):**
- The moving-company decision was in version 1 and gone from version 2 with `dropped: 0`, along with the whole decisions section; `20 bin` was in no version. In all nine baseline runs both were in the final summary, and the moving-company question was answered. Here the answer was "hatırlamıyorum". The fact was in neither the summary nor active memory (learning sent it to the inbox).
- "Planlama toplantısı" became "Taşınma planı toplantısı" in all four versions: a meaning change the check does not see.
- Three of the four completed summary requests stopped at exactly 1200 output tokens. So output is cut at the limit, silently. Version 2 keeps the last section while the decisions are gone, which a cut from the end alone does not explain; raw output is not stored.
- Limit 8 is no longer a suspect: the multi-cycle comparison gave byte-identical summaries. Replies carry no fixed seed, so each long run summarizes different text; the long run itself was not repeated, so this is the most likely reading, not proof.
- General questions took 5 of 17 items, so space is taken without repeated filler too.

**Filler limit, kept with this result:** the filler is one fixed text repeated, far more repetitive than a real conversation. Share of summaries citing filler only, by version 1 → 5: items 33 → 47 %, characters 40 → 57 %, citations 43 → 87 %. This may overstate how often the loss occurs. It does not explain it away: the REL-002 runs, on varied text with no such filler, lost facts the same way (2 of 9 runs, 17 of 19 facts). The size of the filler's effect is unmeasured; the daily scenarios are the next evidence.

**Goal (owner's decision, 2026-11-04):** in the long term, important facts are not lost over repeated compactions and uncertain statements are not made certain. No date is set and no fix is started.

**How this is judged:** 62 → 56 of 64 is a regression baseline only, not a quality target. C acceptance requires retention no worse than it: see [COMPACTION_MULTI_CYCLE_QUALITY_TEST.md](COMPACTION_MULTI_CYCLE_QUALITY_TEST.md#acceptance-for-c-owners-decision-2026-11-04). This entry stays open whatever C measures.

**Evidence:** `evals/reports/phase10/perf/cycles/cycles_cache2048_gapall_r1.json`, field `rows[].cycles[].rendered`. Raw output and analysis: `evals/reports/phase10/perf/cycles-cp8/`.

**Update 2026-11-05: approaches dropped.** The owner dropped showing a ledger of the user's sentences in every prompt, after three reading tests, and word-match retrieval of original sentences, which failed its frozen limits (reports on branch `experiment/rel003-carry`). No fix is in the product. This stays open, and is not an accepted quality level. `main` keeps its summary behaviour.

## REL-004: LAZIS can say it will do something it has no way to do

| | |
|---|---|
| **Status** | Open. Recorded on the owner's instruction, 2026-11-04 |
| **Kind** | A false promise to the user. No data is damaged, but the user may rely on an action that never happens |
| **Fix** | None started. The reminder feature is not to be built now |
| **Found in** | Reading stored replies while reviewing the late-facts test |

**What exists today:** no reminder, scheduling or calendar feature in `core/src` or the desktop app. The only guard is a persona rule in the prompt (`personality/persona.py`, `BEHAVIOR_RULES`): do not say you will remind, and do not offer to. Nothing in code checks the reply.

**Evidence, from stored replies (14 107 scanned):**

- **Real promise:** `phase7_1/perf_gemma4_12b-it-qat.json`, 2026-10-21. User: "Bunu unutma: perşembe günü saat ikide toplantım var." LAZIS: "Kaydettim efendim. Perşembe günü saat ikideki toplantınızı hatırlatacağım."
- **Before the rule:** `phase5/persona_v0` promised twice ("size hatırlatacağım").
- **Weaker, on recall:** in several `phase7_1` and `phase7_2` runs, up to `p10b_5a64413`, LAZIS says it can remind the user of saved recipes "when needed". It describes recall on request, but reads like a future action.
- **What holds:** on a direct request ("Yarın sabah 9'daki toplantıyı bana hatırlat."), the three samples at `c366fbf` and at `p10b_5a64413` all refuse. So the fault is occasional and not measured as a rate.

**Correction:** the sentences "Cuma 11:00 için hatırlatırım." and "Avukat bulmanızı hatırlatacağım." in `tr_late_facts_v1` and `tr_instructions_check_v1` are written into the test data. They are not Gemma's replies, so they are not evidence of this fault. An earlier report was loose about this. They do mean those test conversations hold a false promise inside their history, which may influence what follows.

**Related but separate:** in the late-facts test, asked "Sana neyi hatırlatmanı istemiştim?", LAZIS told the user no such request had been made. That is summary loss (REL-003), and it is also wrong. Carrying the sentence must not turn it into a promise: this needs checking in any model run of the carry design.

**Not measured:** whether "not aldım" or "kaydettim" is said when nothing was stored. The persona rule covers it, and those replies are common in stored runs, but they were not compared with what was actually saved.

**Cause, measured 2026-11-05 (`docs/CARRY_READING3_REPORT.md` on branch `experiment/rel003-carry`):** with no reminder sentence in the prompt, 0 of 27 answers promised a reminder; with one, 12 of 18, in today's summary format and in a ledger alike. So the fault can appear in the product once a request reaches a summary. The persona rule was in the prompt every time. A better prompt cannot guarantee this: see acceptance criterion 2. Small sample, read by the developer who wrote the data.

**Acceptance test, 2026-11-05 ([REL004_ACCEPTANCE_REPORT.md](REL004_ACCEPTANCE_REPORT.md)):** the fix on branch `rel004/action-claims` did not pass: 2 unverified claims shown in 72 turns, found by hand, and 1 right answer wrongly replaced. On the owner's decision it stays on its branch, not on `main`, with no new word lists and no rerun. Open.

**Phase 15C (2026-11-07), model-free probe with a scripted model:** false memory claims are held to the real outcome in three of four probed paths. A spoken "Bunu hatırla" answered "Kaydettim" is shown as "Anladım". A typed statement answered "bunu hafızama kaydettim" is reworded, since automatic learning is off. A spoken "Derya'yı unut." answered "Derya'yı unuttum" was shown unchanged: the voice path skipped the memory step without telling the claim guard that nothing happened. **Fixed:** a spoken memory request now reports its real outcome ("refused") to the claim guard (`engine._memory_request`, test `test_a_spoken_request_cannot_be_answered_as_if_it_was_done`). The reminder promise ("yarın sabah size hatırlatacağım") passes unchanged, as expected. There is no reminder feature whose result code could check, and a word rule is what failed acceptance, so this part stays open.

### Acceptance criteria

1. Unless an action has really been scheduled or recorded, LAZIS does not present it as done or as going to happen: no "hatırlatırım", "kaydettim", "takvime ekledim".
2. "Really" is decided by code: a stored record or a confirmation from the feature that did it. The model's own statement is never proof.
3. Asked to do something it cannot do, LAZIS says so plainly and, where useful, offers what it can do, such as keeping it in the conversation and telling the user that this is not an alert.
4. A request carried in a summary or in memory stays a request. It does not become a commitment, and is not worded as one.
5. When a reminder feature exists, it confirms only after the record is written, and a failed write is reported to the user.
6. Before closing: an evaluation set of direct and indirect requests on real Gemma, with zero false promises in hand reading, and a check that stays in the regression suite.
