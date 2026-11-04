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

- Six facts were lost at a rewrite: `vejetaryen`, `cuma`, `8 bin`, `Kaş`, `Mavi Koy`, `35 bin`. Every one reports `dropped: 0`. `Kuzey` and `15 Aralık` were never in the first summary; they are the two already missing from the 126/128 measure.
- No interruptions, no user traffic and no memory pressure in this test, so the loss needs none of them.
- Seed 7 lost 1 fact, seed 11 lost 7. Two seeds show large effects only.
- **The word check undercounts.** Read by hand: "Kaş'a otobüsle" left with the same rewrite in D5 seed 11, and "Ayşe: kız kardeşi" left at version 3 in D1 in both seeds while the word `Ayşe` stayed. So the real figure is worse than 56 of 64. The 50 summaries have not all been scored claim by claim.

**Why the audit does not see it:**

1. **It measures something else.** `dropped_items` counts items in the model's *new output* that fail the evidence check (`verify_items`, `compaction.py`). A fact the model does not write is never an input. It guards against invention, not loss.
2. **Nothing compares versions.** The previous summary goes to the model only as text with the request to keep valid items (rule 9, `prompts.py`). No code checks that they were kept.
3. **`kept_items` is a net count of the newest version.** It can rise while a fact is gone: filler items replace it (D5 seed 7: 8 → 16 at version 4 with `vejetaryen` still missing).
4. **Two more paths lose text uncounted.** `parse_summary` keeps only the complete items of output cut at the token limit, with no count or log. `_str` cuts an item's text at 300 characters; this is visible in the data ("Düzenl" in D5 seed 7).
5. **A passing item can still change meaning.** The check compares `quote` with the source. It does not compare `text` or `certain` with `quote`. "Araba kiralama: True (Eski: user reddetti, Yeni: assistant önerisi)" passed in D5 seed 7. This is also how an uncertain fact could be made certain; the summaries here did not show that happening.

**Cause of the omission itself: not established.** Evidence against truncation as the main cause, not proof: three of the four loss events took 38–44 s, well under the 60–64 s plateau, and every lost line was in the first two sections, while a cut would remove the last ones if output follows the schema order. Raw model output is not stored, so this cannot be settled from these reports. Whether the filler crowds out facts is unknown; see below.

**Replaying other detectors over the stored summaries** (`evals/runners/p10p_loss_audit_replay.py`, results `evals/reports/phase10/perf/cycles/loss_audit_replay.json`; no model; chosen after the losses were known, on the same data, so these figures do not predict other data):

| Detector | Loss events seen (of 4) | Pairs flagged (of 40) | Note |
|---|---|---|---|
| `dropped_items` > 0 | 0 | 0 | |
| `kept_items` fell | 4 | 17 | Mostly no real fact behind it |
| A dialogue message is no longer cited | 3 | 4 | 4 of 6 facts. Misses a fact whose message is still cited for something else (`vejetaryen` #8, `35 bin` #6). The fourth flag is a real unscored line. Also flags `#7` in exactly the two REL-002 runs (3 flags in 25 long-run pairs) |
| A previous line has words found nowhere in the new text | 4 | 10 | Besides the 4: `kız kardeşi` twice (word check missed it), a breakfast line twice, rewording twice. Noisy on the long runs (10 of 25 pairs; those read were mostly merged lines). Candidates to read, not a verdict |

**Filler limit, kept with this result:** the filler is one fixed text repeated, far more repetitive than a real conversation. Share of summaries citing filler only, by version 1 → 5: items 33 → 47 %, characters 40 → 57 %, citations 43 → 87 %. This may overstate how often the loss occurs. It does not explain it away: the REL-002 runs, on varied text with no such filler, lost facts the same way (2 of 9 runs, 17 of 19 facts). The size of the filler's effect is unmeasured; the daily scenarios are the next evidence.

**Goal (owner's decision, 2026-11-04):** in the long term, important facts are not lost over repeated compactions and uncertain statements are not made certain. No date is set and no fix is started.

**How this is judged:** 62 → 56 of 64 is a regression baseline only, not a quality target. C acceptance requires retention no worse than it: see [COMPACTION_MULTI_CYCLE_QUALITY_TEST.md](COMPACTION_MULTI_CYCLE_QUALITY_TEST.md#acceptance-for-c-owners-decision-2026-11-04). This entry stays open whatever C measures.

**Evidence:** `evals/reports/phase10/perf/cycles/cycles_cache2048_gapall_r1.json`, field `rows[].cycles[].rendered`.
