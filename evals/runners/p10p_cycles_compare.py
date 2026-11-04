"""Compare a multi-cycle run with the limit 8 baseline, version by version. No model, no profile.

    uv run --project core python evals/runners/p10p_cycles_compare.py \\
        --new evals/reports/phase10/perf/fix3-short/fix3-short_cache2048_gapshort_r1.json \\
        --turns evals/reports/phase10/perf/fix3-short/fix3-short_r1_progress/gapshort.turns.jsonl

Shows, for the conversations the new run holds: how each output ended, which sections it reached, the
word check, the claim set, what a rewrite may have lost, and the answers. Candidates to read by hand.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from p10p_claim_score import DATA as CLAIMS
from p10p_claim_score import rule

from lazis.conversation.compaction import audit_rewrite, parse_summary

SUMMARY_OUTPUT_ORDER = ("decisions", "instructions", "constraints", "people", "goals", "topics", "open_questions", "assistant_notes")  # s3-v4/v5 order: on branch experiment/rel003-s3-v5  # fmt: skip
PERF = Path(__file__).resolve().parents[2] / "evals/reports/phase10/perf"
BASE_REPORT = PERF / "cycles-cp8/cycles-cp8_cache2048_gapall_r1.json"
BASE_TURNS = PERF / "cycles-cp8/cycles-cp8_r1_progress/gapall.turns.jsonl"
CRITICAL = ("decisions", "instructions", "constraints", "people")


def calls(path: Path) -> dict[tuple[str, int, int], dict[str, Any]]:
    out: dict[tuple[str, int, int], dict[str, Any]] = {}
    last: dict[str, Any] = {}
    for line in path.read_text("utf-8").splitlines():
        row = json.loads(line)
        if "summary_call" in row:
            last = row["summary_call"]
        elif "i" in row and "cycle" in row:
            out[(row["dialogue"], row["seed"], row["cycle"])] = last
    return out


def reached(raw: str) -> list[str]:
    found = [(raw.find(f'"{k}"'), k) for k in SUMMARY_OUTPUT_ORDER if f'"{k}"' in raw]
    return [k for _, k in sorted(found)]


def one(
    row: dict[str, Any], cycle: dict[str, Any], call: dict[str, Any], before: dict[str, Any] | None
) -> dict[str, Any]:
    parsed = parse_summary(call["raw"]) or {}
    audit = audit_rewrite(before, parsed)
    order = reached(call["raw"])
    return {
        "output_tokens": call.get("output_tokens"), "done_reason": call.get("done_reason"), "parse": call["parse"],
        "at_limit": call["at_limit"], "order": order, "critical_reached": [k for k in CRITICAL if k in order],
        "items": call["items"], "kept": cycle["kept"], "dropped": cycle["dropped"], "seconds": cycle["s"],
        "missing_words": cycle["missing"], "possibly_lost_user": audit.lost_by("user"),
        "became_certain": audit.became_certain, "uncertain": cycle["uncertain"], "rendered": cycle["rendered"],
    }  # fmt: skip


def side(
    report: dict[str, Any], turns: dict[tuple[str, int, int], dict[str, Any]], key: tuple[str, int]
) -> dict[int, dict[str, Any]]:
    row = next(r for r in report["rows"] if (r["dialogue"], r["seed"]) == key)
    out: dict[int, dict[str, Any]] = {}
    before: dict[str, Any] | None = None
    for c in row["cycles"]:
        call = turns[(key[0], key[1], c["cycle"])]
        out[c["cycle"]] = one(row, c, call, before)
        before = parse_summary(call["raw"]) or {}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", required=True)
    ap.add_argument("--turns", required=True)
    a = ap.parse_args()
    new = json.loads(Path(a.new).read_text("utf-8"))
    base = json.loads(BASE_REPORT.read_text("utf-8"))
    new_turns, base_turns = calls(Path(a.turns)), calls(BASE_TURNS)
    claims = json.loads(CLAIMS.read_text("utf-8"))["claims"]
    result: list[dict[str, Any]] = []
    for r in new["rows"]:
        key = (r["dialogue"], r["seed"])
        old_side, new_side = side(base, base_turns, key), side(new, new_turns, key)
        for v, n in new_side.items():
            o = old_side[v]
            verdicts = {
                c["id"]: {"old": rule(c, o["rendered"])["verdict"], "new": rule(c, n["rendered"])["verdict"]}
                for c in claims if c["dialogue"] == r["dialogue"]
            }  # fmt: skip
            changed = {k: x for k, x in verdicts.items() if x["old"] != x["new"]}
            result.append(
                {
                    "conversation": f"{key[0]} seed {key[1]}",
                    "version": v,
                    "old": o,
                    "new": n,
                    "claims_changed": changed,
                }
            )
            print(key[0], key[1], "v", v, "| old", o["output_tokens"], o["parse"], "reach", [k[:4] for k in o["critical_reached"]],
                  "lost", o["possibly_lost_user"], "miss", o["missing_words"], "| new", n["output_tokens"], n["parse"],
                  "reach", [k[:4] for k in n["critical_reached"]], "lost", n["possibly_lost_user"], "miss", n["missing_words"],
                  "order", [k[:4] for k in n["order"]], "| claims", changed, "| certain", n["became_certain"], n["uncertain"])  # fmt: skip
        old_row = next(x for x in base["rows"] if (x["dialogue"], x["seed"]) == key)
        for qo, qn in zip(old_row["answers"], r["answers"], strict=False):
            print(
                "   Q",
                qn["q"][:36],
                "old",
                qo["pass"],
                "new",
                qn["pass"],
                "|",
                qn["answer"][:110].replace("\\n", " "),
            )
    Path(a.new).with_suffix(".compare.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n", "utf-8"
    )


if __name__ == "__main__":
    main()
