# Compaction: fact retention over several cycles (test design)

**Status:** built as `evals/runners/p10p_compaction_cycles.py`; checked on a short trial only (`--gaps smoke`: one dialogue, two summary versions, one question). **Baseline run 2026-11-04 on `703941c` (results below).** Required by the owner before changes A, B or C can be accepted (2026-11-03). No product code, summary prompt or memory rule changes for it.

## Why

The current quality measure (126/128, `p10p_compaction_long.py --quality`) writes a dialogue, compacts it once through `engine.compact_now` and looks for the expected facts in that one summary. A real conversation rewrites its summary again and again.

The long baseline runs show this matters. In [REL-002](RELIABILITY_ISSUES.md#rel-002-a-stored-fact-about-a-person-cannot-be-recalled) a fact is present in summary v1, gone from v2 with `dropped: 0`, and the user is told there is no such information. The single-compaction measure cannot see this.

## Questions it must answer

1. Does each fact survive every rewrite, and at which version is it first lost?
2. Is a loss reported (`dropped_items`), or silent?
3. Is an uncertain fact still uncertain, and does a replaced value stay replaced?
4. When the summary has lost a fact, can the user still get it, and from where?
5. Do A, B or C make any of this worse than the unchanged code?

## Method

**Data:** `evals/datasets/tr_compaction_v1.json`, the same five dialogues and expected facts as the single-compaction measure, plus the 40-message set of the long runs. Synthetic data, throwaway encrypted profiles, the private test runtime.

**One conversation:**
1. Write the dialogue's messages, then compact (summary v1).
2. Add a fixed block of unrelated questions and answers, large enough that compaction has older messages to take in. Compact again.
3. Repeat to five summary versions. The long runs produced three or four, so this goes one past what was seen.
4. Ask the dataset's questions about the facts, in the same conversation, with the facts outside the recent window.

A cycle in which `compact_now` returns False fails the conversation visibly; it is never skipped. Each compaction runs in the foreground, one at a time, with no user waiting: this test measures content, not latency. Latency stays with the long runs.

**Repeats:** seeds 7 and 11, the same as now, with the production `keep_recent_tokens` setting. Summary requests stay byte-identical to the engine's, apart from the seed.

**Time, estimated:** 5 dialogues × 2 seeds × 5 compactions at about 45 s each is about 40 minutes per code version. It runs under the supervisor with the same start conditions and stop rules.

## What is recorded

| Per fact, per summary version | Per conversation | At the question |
|---|---|---|
| Present or missing | First version with a loss | Answer text |
| Marked uncertain, where the fact is | `kept_items`, `dropped_items` per version | Whether the active summary held the fact |
| An old value present as current | Silent loss: fact missing while `dropped_items` is 0 | Whether a memory held it **at that moment** |
| | Hand-read rendered summaries | Whether recall offered it to the model |

**As built:** this runner keeps learning off and writes the history directly, so it reads the summary alone and the memory column does not apply. The daily scenarios (`p10p_daily.py`) learn normally and record, at each question, whether the fact was in the summary, in memory and in the prompt at that moment. Both are needed to tell a summary loss from a recall failure. No product change was needed for this.

**Scoring:** automatic checks count words, and they have missed real faults before, so every rendered summary with a loss and every answer is read by hand. The word check alone also cannot say whether uncertainty is kept, so that column is judged by hand against the dataset.

## How it is used

1. **Baseline first:** run on unchanged code before A starts. This gives the figure to compare with, as 126/128 does for one compaction.
2. **Each of A, B, C and the combination:** same data and seeds, compared per conversation with the baseline.
3. **Separate columns:** losses already in the baseline stay in the general reliability reporting (REL-001, REL-002). New or more frequent losses count against the change being tested.

**Pass criteria for C:** see [the owner's decision below](#acceptance-for-c-owners-decision-2026-11-04). B and A are not approved; their criteria are set if they come up.

**Known limit:** two seeds show large effects only. A small difference between code versions cannot be told from model variation with this sample, and the report must say so.

**Seen in the short trial, to read for in the baseline:** the unrelated filler questions appear in the summary under open questions. Whether they push out real facts is unknown.

## Baseline result (2026-11-04)

Report: `evals/reports/phase10/perf/cycles/cycles_cache2048_gapall_r1.json`. 50 compactions in 46 minutes, none failed. Pressure normal throughout, swap flat at 0.6 GB, other programs 9.7–11.5 GB.

| Version | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| Facts kept of 64 | 62 | 61 | 59 | 59 | 56 |

Seed 7 lost 1 fact, seed 11 lost 7. Answers: 28 of 32 passed. Three misses are real (two restaurant answers without the vegetarian diet, one "no information" on the destination); "Araba kiralama planınız şu an için geçerli değil" may be a checker miss.

**Read by hand:**
- The old values flagged read as past, not current ("React yerine Vue", "09:00 olarak planlanmıştı").
- The word count understates one loss. In D5 seed 11, version 5 lost the whole lines for the route, transport and budget, so "otobüs" went too, and no word in the check covers it.
- In D5 seed 11 the summary still holds "Selin, vejetaryen" and the restaurant answer still leaves it out: the reply not using a fact, as noted under REL-002.
- The filler fills the summaries: up to 10 lines of repeated questions and up to 117 message citations. By version 5, 47 % of items, 57 % of characters and 87 % of citations are about the filler alone. Whether real conversations do this is what the daily scenarios show. **This limit stays attached to every use of these figures:** they may overstate how often the loss occurs.
- Many compactions took a nearly constant 60–64 s. That may be the output limit (`summary_max_tokens` 1200), but this runner does not record output tokens. `p10p_daily.py` does, so check it there before planning C.

## Acceptance for C (owner's decision, 2026-11-04)

Speed alone does not accept C. Knowledge retention after several compactions is a required criterion, and **a result worse than the current loss is not accepted.** The three conditions marked below were approved by the owner on the same day.

**The figures are a regression baseline only, not LAZIS's memory quality target (owner's decision).** 62 → 56 of 64 says how much worse C may not be. The long-term goal is that important facts are not lost over repeated compactions and that uncertain statements are not made certain. [REL-003](RELIABILITY_ISSUES.md#rel-003-facts-disappear-silently-when-a-summary-is-rewritten) stays open.

Same data, same seeds, compared per conversation with this baseline:

| Measure | Baseline, the limit for C |
|---|---|
| Facts kept of 64, versions 1 to 5 | At least 62, 61, 59, 59, 56 |
| Conversations with a silent loss, versions 1 to 5 | At most 0, 1, 3, 3, 4 |
| Answers | At least 28 of 32, no new real miss |
| Uncertain facts | Stay uncertain in every version |
| Replaced values | Never read as current |

- **No offsetting (approved).** A new loss is not balanced by another fact coming back. A fact the baseline kept and C lost is read by hand and reported on its own, and the owner decides on it.
- **No explaining it away.** A result under the limit is a failure, not noise. Two seeds cannot show small differences, so a pass does not prove C is equal; a failure is rerun only if the owner decides. The limits are not relaxed.
- **The test must reach C's code (approved).** Retention is measured in scenarios where C actually runs. This runner compacts through `compact_now` with no user waiting. C changes what happens when a turn meets compaction, so this runner alone may never run C's path and would pass trivially. C also needs retention measured on the daily scenarios against their baseline, and the C plan must show which path each test runs.
- **Whole conversation, not only per version (approved).** C may change how many rewrites a conversation goes through. Since loss grows per rewrite, a per-version figure can look fine while the conversation ends up worse. So the total loss at the end of the conversation and the number of rewrites are compared too.
- **Words are not enough.** Word or embedding matching alone is never evidence of accuracy (owner's decision). Every summary and answer is still read by hand, including the losses the word check misses (`otobüs`, `kız kardeşi`).
- **Records are not deleted.** See below.

## Stored records (owner's decision, 2026-11-04)

Stored conversation messages and summary records are never deleted for the sake of speed, under any condition. This holds today: a new summary marks the old one `superseded`, `reset_context` marks summaries `invalidated`, and rows are removed only when the user deletes a conversation (`repository.delete_conversation`), which this rule does not concern. C must not add any other removal, and its acceptance checks that message and summary rows only grow during a run.

## How meaning and uncertainty can be checked (review, no change made)

**Owner's decision (2026-11-04):** the hand-verified claim set (subject, value, source, certainty) is accepted as the recommended method for the next evaluation. No comprehensive new system is built now: only the scope and cost of a small sample go into the C plan ([COMPACTION_LATENCY_PROPOSAL.md](COMPACTION_LATENCY_PROPOSAL.md), §9). No model-based automatic judge is added for now.

Why word matching fails, from this data: it missed real losses (`otobüs`, `kız kardeşi`), raised false alarms on correct past mentions ("React yerine Vue"), and cannot tell whether a word still belongs to the right fact, or whether it is hedged. Figures for the detectors are under REL-003.

| Method | What it can show | What it cannot | Cost | Assessment |
|---|---|---|---|---|
| **Claim-level gold set** | Each fact written as a claim: subject, value, source message, status (certain, uncertain, replaced). Passes only if the parts are on one item with the right status | Paraphrase beyond the listed forms; facts nobody listed | Hand-written, no model, can rescore stored summaries | **Accepted as the recommended method.** Not built; small sample planned |
| **Version comparison** | Items and citations that vanish between versions, with no gold set, so it also works on real conversations | Whether what vanished mattered; a fact merged under a citation that stays | No model | **Recommended as a candidate list** for hand reading |
| **Item and source status check** | `current` and `certain` flipping between versions on the same claim | Implicit hedges | No model; needs the stored JSON content | Recommended with the gold set |
| **Hedge words against the mark** | A hedge in the cited message but none on the item | Which clause the hedge belongs to | No model | **Not usable alone.** Replay over 413 lines: 4 flags, all "Mehmet: iş arkadaşı", where the relation is certain and only the trip is hedged. 13 lines from firm messages are marked uncertain ("Koşu yapılacak"), so the mark is also overused |
| **Model as judge** (Gemma, test time only) | Paraphrase and hedging per claim | Its own errors, which may match the summarizer's: same model | One model call per claim | **Not added for now (owner's decision).** |
| **Embedding similarity** | Same topic | "Gidecek" and "galiba gidecek" are close in meaning space: this is exactly the difference that matters | Would need a model; downloads are out of bounds | **Rejected** for this purpose |
| **Questions at the end** | What the user actually gets | Why it failed | Already in the runners | Keep; the daily runner also records where the fact was at that moment |

**Uncertainty evidence is thin.** "Mehmet stayed hedged in all versions" rests on one uncertain fact in two conversations, the only uncertain fact in the gold set. A gold set for this needs more uncertain claims, including implicit ones. Hand reading stays the final judge in every case.

**Possible product changes, none made or proposed for approval yet:** report vanished items beside `dropped_items`, and count cut output. These change no behaviour but need the owner's approval like any product code.

## Not in scope

Fixing REL-001 or REL-002, changing the summary prompt or memory rules, and any change to product code.
