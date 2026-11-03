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

**Measured over several compactions (multi-cycle test, 2026-11-04, code `703941c`, 10 conversations, five summary versions, learning off):**

| Summary version | Facts missing of 64 | Conversations with a loss since an earlier version |
|---|---|---|
| 1 | 2 | 0 |
| 2 | 3 | 1 |
| 3 | 5 | 3 |
| 4 | 5 | 3 |
| 5 | 8 | 4 |

- Six facts were lost at a rewrite: `vejetaryen`, `cuma`, `8 bin`, `Kaş`, `Mavi Koy`, `35 bin`. Every one of these losses reports `dropped: 0`. The other two, `Kuzey` and `15 Aralık`, were never in the first summary; they are the same two missing from the 126/128 measure.
- This test has no interruptions, no user traffic and no memory pressure. So the loss does not need any of them.
- The Mehmet line survived all five versions in both seeds here, so the specific case above was not reproduced.
- Limit: the filler is one fixed text repeated, far more repetitive than a real conversation, and it fills the summary. This may overstate the loss. Word checks only; two seeds.

**How this is judged:** no summary or memory rule changes during the compaction latency work. It is a baseline fault, and performance acceptance judges new errors caused by changes A, B or C separately from it. The summary prompt stays unchanged. The fault stays open in the general reliability reporting.

**Evidence:** `evals/reports/phase10/perf/baseline_cache2048_gap6_r2.json` and `..._gap6_r3.json`, fields `turns[32]`, `summaries`, `memories`.
