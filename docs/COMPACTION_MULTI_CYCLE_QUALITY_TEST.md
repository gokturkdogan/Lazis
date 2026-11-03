# Compaction: fact retention over several cycles (test design)

**Status:** built as `evals/runners/p10p_compaction_cycles.py`; checked on a short trial only (`--gaps smoke`: one dialogue, two summary versions, one question). **The baseline has not been run.** Required by the owner before changes A, B or C can be accepted (2026-11-03). No product code, summary prompt or memory rule changes for it.

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

**Pass criteria, proposed for the owner's decision once the baseline exists:**
- No change may lose a fact, or lose it earlier, more often than the baseline beyond what two seeds can show; any such case is read by hand and reported, not averaged away.
- No new silent loss, uncertain fact made certain, or old value restored.
- An absolute target for retention at version 5. It cannot be set honestly before the baseline is measured.

**Known limit:** two seeds show large effects only. A small difference between code versions cannot be told from model variation with this sample, and the report must say so.

**Seen in the short trial, to read for in the baseline:** the unrelated filler questions appear in the summary under open questions. Whether they push out real facts is unknown.

## Not in scope

Fixing REL-001 or REL-002, changing the summary prompt or memory rules, and any change to product code.
