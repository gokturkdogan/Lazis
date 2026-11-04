"""What the 1200 token output limit does, from the raw output kept by p10p_cycles_checkpoints.py.

Reads reports only: no model, no profile, no product code. Writes
evals/reports/phase10/perf/cycles-cp8/limit_analysis.json. Lines flagged here are candidates that were
read by hand, not a verdict.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from p10p_loss_audit_replay import compare, parse_lines

PERF = Path(__file__).resolve().parents[2] / "evals/reports/phase10/perf"
DATASET = Path(__file__).resolve().parents[2] / "evals/datasets/tr_compaction_v1.json"
BASE = PERF / "cycles-cp8"
SECTION_ORDER = (
    "goals",
    "topics",
    "decisions",
    "open_questions",
    "constraints",
    "people",
    "instructions",
    "assistant_notes",
)


def key_order(raw: str) -> list[str]:
    found = [(raw.find(f'"{k}"'), k) for k in SECTION_ORDER if f'"{k}"' in raw]
    return [k for _, k in sorted(found)]


def calls_by_version() -> dict[tuple[str, int, int], list[dict[str, Any]]]:
    out: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
    buf: list[dict[str, Any]] = []
    for line in (BASE / "cycles-cp8_r1_progress/gapall.turns.jsonl").read_text().splitlines():
        row = json.loads(line)
        if "summary_call" in row:
            buf.append(row["summary_call"])
        elif "i" in row and "cycle" in row:
            out[(row["dialogue"], row["seed"], row["cycle"])] = buf
            buf = []
    return out


def main() -> None:
    report = json.loads((BASE / "cycles-cp8_cache2048_gapall_r1.json").read_text())
    dialogues = {d["id"]: d for d in json.loads(DATASET.read_text())["dialogues"]}
    calls = calls_by_version()
    rows: list[dict[str, Any]] = []
    for r in report["rows"]:
        limit = len(dialogues[r["dialogue"]]["messages"])
        prev = None
        for c in r["cycles"]:
            call = calls[(r["dialogue"], r["seed"], c["cycle"])][-1]
            raw = call["raw"]
            order = key_order(raw)
            refs = sum(len(x) for x in re.findall(r'"refs"\s*:\s*\[[^\]]*\]', raw))
            quotes = sum(len(x) for x in re.findall(r'"quote"\s*:\s*"[^"]*"', raw))
            lines = parse_lines(c["rendered"])
            filler_only = sum(1 for _, rf in lines if rf and all(x > limit for x in rf))
            row: dict[str, Any] = {
                "conversation": f"{r['dialogue']} seed {r['seed']}", "version": c["cycle"],
                "output_tokens": call.get("output_tokens"), "done_reason": call.get("done_reason"),
                "at_limit": call["at_limit"], "parse": call["parse"], "items": call["items"],
                "section_order": order, "reached_last_section": bool(order) and order[-1] == SECTION_ORDER[-1],
                "last_section_in_raw": order[-1] if order else None, "tail": raw[-90:],
                "raw_chars": len(raw), "refs_share_pct": round(100 * refs / max(1, len(raw))),
                "quotes_share_pct": round(100 * quotes / max(1, len(raw))),
                "filler_only_items": filler_only, "items_total": len(lines),
                "new_word_losses": [x for x in c["lost_since_earlier"] if not prev or x not in prev["lost_since_earlier"]],
                "lines_with_words_gone": [],
            }  # fmt: skip
            if prev is not None:
                _, orphans = compare(prev["rendered"], c["rendered"])
                row["lines_with_words_gone"] = [
                    o for o in orphans if any(x <= limit for x in o["refs"])
                ]
            rows.append(row)
            prev = c

    def summary(group: list[dict[str, Any]]) -> dict[str, Any]:
        rewrites = [x for x in group if x["version"] > 1]
        return {
            "versions": len(group), "rewrites": len(rewrites),
            "rewrites_with_word_loss": sum(bool(x["new_word_losses"]) for x in rewrites),
            "facts_lost_by_word": sum(len(x["new_word_losses"]) for x in rewrites),
            "rewrites_with_a_line_gone": sum(bool(x["lines_with_words_gone"]) for x in rewrites),
            "lines_gone": sum(len(x["lines_with_words_gone"]) for x in rewrites),
            "mean_items": round(sum(x["items_total"] for x in group) / max(1, len(group)), 1),
            "mean_filler_only_items": round(sum(x["filler_only_items"] for x in group) / max(1, len(group)), 1),
            "mean_refs_share_pct": round(sum(x["refs_share_pct"] for x in group) / max(1, len(group))),
            "mean_quotes_share_pct": round(sum(x["quotes_share_pct"] for x in group) / max(1, len(group))),
            "reached_last_section": sum(x["reached_last_section"] for x in group),
            "last_section_in_raw": {k: sum(x["last_section_in_raw"] == k for x in group) for k in SECTION_ORDER},
        }  # fmt: skip

    result = {"at_limit": summary([x for x in rows if x["at_limit"]]),
              "not_at_limit": summary([x for x in rows if not x["at_limit"]]), "rows": rows}  # fmt: skip
    (BASE / "limit_analysis.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1) + "\n"
    )
    print(
        json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=1)
    )
    for x in rows:
        if x["at_limit"] or x["lines_with_words_gone"] or x["new_word_losses"]:
            print(x["conversation"], "v", x["version"], "out", x["output_tokens"], x["done_reason"], x["parse"], "order", [s[:4] for s in x["section_order"]],
                  "refs%", x["refs_share_pct"], "filler", x["filler_only_items"], "/", x["items_total"], "LOST", x["new_word_losses"],
                  [(o["line"][:48], o["words_gone"][:4]) for o in x["lines_with_words_gone"]])  # fmt: skip


if __name__ == "__main__":
    main()
