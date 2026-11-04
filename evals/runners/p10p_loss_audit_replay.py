"""Replay candidate loss detectors over stored summaries: which of them see a real loss?

Reads reports only. No model, no profile, no product code. It exists to answer why the loss
audit reports ``dropped: 0`` for facts that are gone, and what could see them instead. See
docs/RELIABILITY_ISSUES.md (REL-003).

The detectors were chosen after the losses were known, on the same data, so the detection
figures describe this data; they do not predict other data. Alarms are candidates to read by
hand, never a verdict.

Usage: uv run --project core python evals/runners/p10p_loss_audit_replay.py
"""

from __future__ import annotations

import glob
import itertools
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
PERF = REPO / "evals/reports/phase10/perf"
OUT = PERF / "cycles/loss_audit_replay.json"
DATASET = REPO / "evals/datasets/tr_compaction_v1.json"

UNCERTAIN_MARK = "(belirsiz)"
HEDGES = (
    "galiba",
    "belki",
    "sanırım",
    "muhtemelen",
    "kesin değil",
    "düşünüyorum",
    "olabilir",
    "emin değil",
)
# Words of the summary's own frame: their absence says nothing about a fact.
FRAME = {"kulla", "belir", "eski", "yeni", "user", "assis", "true", "false"}

Line = tuple[str, list[int]]


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("İ", "i").replace("I", "ı").lower()
    return re.sub(r"[^\w\s]", " ", text)


def parse_lines(rendered: str) -> list[Line]:
    """The item lines of a rendered summary: text and cited message numbers."""
    out: list[Line] = []
    for line in rendered.splitlines()[1:]:
        if not line.startswith("- "):
            continue
        cite = re.search(r"\[(#[^\]]+)\]\s*$", line)
        refs = [int(n) for n in re.findall(r"#(\d+)", cite.group(1))] if cite else []
        out.append((line[2 : cite.start()].strip() if cite else line[2:], refs))
    return out


def stems(text: str) -> set[str]:
    """Word starts, a crude way past Turkish suffixes. This is why alarms are only candidates."""
    words = normalize(text).split()
    return {w[:5] for w in words if len(w) >= 3 or any(c.isdigit() for c in w)}


def compare(prev: str, cur: str) -> tuple[list[int], list[dict[str, Any]]]:
    """Messages no longer cited, and previous lines with words found nowhere in the new text."""
    prev_lines, cur_lines = parse_lines(prev), parse_lines(cur)
    cited_before = {r for _, refs in prev_lines for r in refs}
    cited_now = {r for _, refs in cur_lines for r in refs}
    now = stems(cur)
    orphans: list[dict[str, Any]] = []
    for body, refs in prev_lines:
        gone = sorted(stems(body) - now - FRAME)
        if gone:
            orphans.append({"line": body[:90], "refs": refs[:4], "words_gone": gone})
    return sorted(cited_before - cited_now), orphans


def replay_cycles(report: dict[str, Any], dialogues: dict[str, Any]) -> dict[str, Any]:
    counts = dict.fromkeys(
        (
            "pairs",
            "loss_events",
            "dropped_above_zero",
            "dropped_on_loss",
            "kept_fell",
            "kept_fell_on_loss",
            "citation_gone",
            "citation_gone_on_loss",
            "line_words_gone",
            "line_words_gone_on_loss",
        ),
        0,
    )
    alarms: list[dict[str, Any]] = []
    facts = {"lost_at_rewrite": 0, "citation_gone_sees": 0}
    for row in report["rows"]:
        messages = dialogues[row["dialogue"]]["messages"]
        expected = {fact: seq for fact, seq in dialogues[row["dialogue"]]["summary_expect"]}
        for a, b in itertools.pairwise(row["cycles"]):
            new = [f for f in b["lost_since_earlier"] if f not in a["lost_since_earlier"]]
            gone, orphans = compare(a["rendered"], b["rendered"])
            # Only the dialogue's own messages: the filler has no facts to lose.
            gone = [r for r in gone if r <= len(messages)]
            orphans = [o for o in orphans if any(r <= len(messages) for r in o["refs"])]
            seen = {
                "dropped": b["dropped"] > 0,
                "kept_fell": b["kept"] < a["kept"],
                "citation_gone": bool(gone),
                "line_words_gone": bool(orphans),
            }
            counts["pairs"] += 1
            counts["dropped_above_zero"] += seen["dropped"]
            for name in ("kept_fell", "citation_gone", "line_words_gone"):
                counts[name] += seen[name]
            if new:
                counts["loss_events"] += 1
                counts["dropped_on_loss"] += seen["dropped"]
                for name in ("kept_fell", "citation_gone", "line_words_gone"):
                    counts[f"{name}_on_loss"] += seen[name]
                facts["lost_at_rewrite"] += len(new)
                facts["citation_gone_sees"] += sum(1 for f in new if expected.get(f) in gone)
            if gone or orphans or new:
                alarms.append(
                    {
                        "conversation": f"{row['dialogue']} seed {row['seed']}",
                        "versions": [a["version"], b["version"]],
                        "seconds": b["s"],
                        "kept": [a["kept"], b["kept"]],
                        "word_check_lost": new,
                        "citations_gone": gone,
                        "lines_with_words_gone": orphans,
                    }
                )
    return {"counts": counts, "facts": facts, "alarms": alarms}


def filler_share(report: dict[str, Any], dialogues: dict[str, Any]) -> dict[str, Any]:
    """How much of each summary version is about the repeated filler alone."""
    totals: dict[int, list[int]] = {}
    for row in report["rows"]:
        limit = len(dialogues[row["dialogue"]]["messages"])
        for cycle in row["cycles"]:
            lines = parse_lines(cycle["rendered"])
            only = [body for body, refs in lines if refs and all(r > limit for r in refs)]
            t = totals.setdefault(cycle["version"], [0, 0, 0, 0, 0, 0])
            t[0] += len(only)
            t[1] += len(lines)
            t[2] += sum(len(b) for b in only)
            t[3] += sum(len(b) for b, _ in lines)
            t[4] += sum(1 for _, refs in lines for r in refs if r > limit)
            t[5] += sum(len(refs) for _, refs in lines)
    return {
        str(v): {
            "items": f"{t[0]}/{t[1]}",
            "items_pct": round(100 * t[0] / t[1]),
            "chars_pct": round(100 * t[2] / t[3]),
            "citations_pct": round(100 * t[4] / t[5]),
        }
        for v, t in sorted(totals.items())
    }


def uncertainty_rule(report: dict[str, Any], dialogues: dict[str, Any]) -> dict[str, Any]:
    """A hedge word in the cited user message, against the mark on the summary line."""
    lines_total = 0
    unmarked: dict[str, Any] = {}
    overmarked: dict[str, Any] = {}
    for row in report["rows"]:
        messages = dialogues[row["dialogue"]]["messages"]
        for cycle in row["cycles"]:
            for body, refs in parse_lines(cycle["rendered"]):
                said = [
                    messages[r - 1][1].lower()
                    for r in refs
                    if r <= len(messages) and messages[r - 1][0] == "user"
                ]
                if not said:
                    continue
                lines_total += 1
                hedged = any(h in text for text in said for h in HEDGES)
                marked = body.endswith(UNCERTAIN_MARK) or any(h in body.lower() for h in HEDGES)
                key = f"{row['dialogue']}: {body[:70]}"
                if hedged and not marked:
                    unmarked[key] = unmarked.get(key, 0) + 1
                if marked and not hedged:
                    overmarked[key] = overmarked.get(key, 0) + 1
    return {
        "user_backed_lines": lines_total,
        "source_hedged_line_unmarked": unmarked,
        "source_firm_line_marked": overmarked,
    }


def replay_long_runs() -> list[dict[str, Any]]:
    """The 40-message runs: varied text, no repeated filler, including the REL-002 runs."""
    out: list[dict[str, Any]] = []
    for path in sorted(glob.glob(str(PERF / "baseline*_gap*_r*.json"))):
        report = json.loads(Path(path).read_text(encoding="utf-8"))
        ordered = sorted(report.get("summaries") or [], key=lambda s: s.get("version", 0))
        for a, b in itertools.pairwise(ordered):
            gone, orphans = compare(a["rendered"], b["rendered"])
            out.append(
                {
                    "run": Path(path).stem,
                    "versions": [a["version"], b["version"]],
                    "kept": [a["kept"], b["kept"]],
                    "dropped": b["dropped"],
                    "citations_gone": gone,
                    "lines_with_words_gone": [o["line"] for o in orphans],
                }
            )
    return out


def main() -> None:
    report = json.loads((PERF / "cycles/cycles_cache2048_gapall_r1.json").read_text("utf-8"))
    data = json.loads(DATASET.read_text("utf-8"))
    dialogues = {d["id"]: d for d in data["dialogues"]}
    long_runs = replay_long_runs()
    result = {
        "note": "Detectors chosen after the losses were known, on this data. Candidates only.",
        "cycles": replay_cycles(report, dialogues),
        "filler_share_by_version": filler_share(report, dialogues),
        "uncertainty_rule": uncertainty_rule(report, dialogues),
        "long_runs": {
            "pairs": len(long_runs),
            "pairs_citation_gone": sum(1 for p in long_runs if p["citations_gone"]),
            "pairs_line_words_gone": sum(1 for p in long_runs if p["lines_with_words_gone"]),
            "pairs_dropped_above_zero": sum(1 for p in long_runs if p["dropped"]),
            "detail": long_runs,
        },
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result["cycles"].items() if k != "alarms"}, indent=1))
    print(json.dumps(result["filler_share_by_version"], indent=1))
    print(json.dumps(result["uncertainty_rule"], ensure_ascii=False, indent=1))
    print({k: v for k, v in result["long_runs"].items() if k != "detail"})
    print(
        [(p["run"], p["versions"], p["citations_gone"]) for p in long_runs if p["citations_gone"]]
    )


if __name__ == "__main__":
    main()
