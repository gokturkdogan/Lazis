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

**What was stored** (active memory, origin `stated`, first six baseline runs):

| Run | Predicate / value | Content | Uncertainty kept |
|---|---|---|---|
| gap 30, run 1 | `note` / İzmir | Mehmet 10 Kasım'da İzmir'e gidecek. | **No** |
| gap 30, run 2 | `plan` / Mehmet de galiba 10 Kasım'da İzmir'e gidecek | Mehmet 10 Kasım'da İzmir'e gidecek. | **No** in the content |
| gap 60, run 1 | `note` / İzmir | Mehmet 10 Kasım'da İzmir'e gidecek. | **No** |
| gap 60, run 2 | `note` / İzmir | Mehmet'in 10 Kasım'da İzmir'e gideceği söyleniyor. | Partly |
| gap 6, run 1 | `plan` / Mehmet de galiba 10 Kasım'da İzmir'e gidecek | Mehmet'in 10 Kasım'da İzmir'e gitme ihtimali bulunuyor. | Yes |
| gap 6, run 2 | `plan` / Mehmet de galiba 10 Kasım'da İzmir'e gidecek | Mehmet'in 10 Kasım'da İzmir'e gideceği tahmin ediliyor. | Yes |

Memory jobs were still running when both gap 6 reports were written, so those two memory lists may be incomplete.

**Where it does not appear:** the active summary keeps the uncertainty in five of six runs. In gap 6, run 2 it has no Mehmet line, and that run's reply to the question about Mehmet says there is no record.

**Related, not the same fault:** in gap 30, runs 1 and 2, the reply to the same message speaks of Mehmet "taşınma" (moving house), which the user did not say.

**Cause:** not investigated. The record is written by the memory learning step; the step or rule responsible has not been identified.

**How this is judged (owner's decision, 2026-11-03):**
- Memory learning rules do not change during the compaction latency work.
- Performance acceptance judges new memory or fact errors caused by changes A, B or C, separately from faults already in the system. This fault is measured in the baseline and is not attributed to them.
- This does not close the fault. It stays open in the general reliability reporting.

**Evidence:** `evals/reports/phase10/perf/baseline_cache2048_gap*_r*.json`, fields `memories`, `summaries`, `turns`.
