"""Score stored summaries against the small claim set. No model, no profile, no product code.

    uv run --project core python evals/runners/p10p_claim_score.py

Data: evals/datasets/tr_compaction_claims_sample_v1.json. A claim passes only if its parts are on one
summary item, with the right status. The rule proposes a verdict and every distinct case is read by
hand; a case the rule gets wrong is recorded in ``hand_overrides`` with its reason, and reported as a
false alarm or a miss. Word checks are reported beside it, never as proof.

The set holds known losses on purpose, so it gives NO general loss rate over conversations.
"""

from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PERF = ROOT / "evals/reports/phase10/perf"
DATA = ROOT / "evals/datasets/tr_compaction_claims_sample_v1.json"
DIALOGUES = ROOT / "evals/datasets/tr_compaction_v1.json"
OUT = PERF / "claims/claim_sample_v1.json"
HEDGES = (
    "galiba",
    "belki",
    "sanırım",
    "ihtimal",
    "kesin değil",
    "kesinleş",
    "muhtemel",
    "düşünüyor",
    "planlıyor",
)
OLD_SECTION = "Değiştirilmiş eski kararlar"


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace("İ", "i").replace("I", "ı").lower()
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


def items(rendered: str) -> list[dict[str, str]]:
    section, out = "", []
    for line in rendered.splitlines()[1:]:
        if line.startswith("- "):
            out.append({"section": section, "line": line[2:]})
        elif line.endswith(":"):
            section = line[:-1]
    return out


def on_line(forms: list[str], line: str) -> bool:
    """A form at the start of a word, so that ``kaş`` is not found in ``kaşık`` only by accident of
    position and suffixes still match; ``eş`` must stand as ``eş`` or take a suffix."""
    return any(re.search(rf"\b{re.escape(norm(f))}", line) for f in forms)


def rule(claim: dict[str, Any], rendered: str) -> dict[str, Any]:
    hits = [i for i in items(rendered) if all(on_line(g, norm(i["line"])) for g in claim["all"])]
    best = hits[0] if hits else None
    if claim["status"] == "replaced":
        current = [h for h in hits if not h["section"].startswith(OLD_SECTION)]
        verdict = (
            "replaced_absent"
            if not hits
            else "replaced_as_current"
            if current
            else "replaced_marked_old"
        )
        best = current[0] if current else best
    elif not hits:
        verdict = "lost"
    elif claim["status"] == "uncertain":
        kept = [
            h
            for h in hits
            if h["line"].rstrip(" ]#0123456789,").find("(belirsiz)") >= 0
            or any(x in norm(h["line"]) for x in HEDGES)
        ]
        verdict = "kept_uncertain" if kept else "uncertainty_lost"
        best = kept[0] if kept else best
    else:
        verdict = "kept"
    return {"verdict": verdict, "line": best["line"] if best else None}


def word_check(dialogue: dict[str, Any], rendered: str) -> list[str]:
    text = norm(rendered)
    return [w for w, _ in dialogue["summary_expect"] if norm(w) not in text]


def score_one(
    claim: dict[str, Any],
    where: str,
    rendered: str,
    overrides: dict[tuple[str, str], dict[str, str]],
) -> dict[str, Any]:
    auto = rule(claim, rendered)
    row = {
        "claim": claim["id"],
        "where": where,
        "rule": auto["verdict"],
        "verdict": auto["verdict"],
        "line": auto["line"],
        "override": None,
    }
    key = (claim["id"], auto["line"] or "")
    if key in overrides:
        row["verdict"], row["override"] = overrides[key]["verdict"], overrides[key]["reason"]
    return row


def main() -> None:
    data = json.loads(DATA.read_text("utf-8"))
    claims = {c["id"]: c for c in data["claims"]}
    overrides = {(o["claim"], o["line"]): o for o in data["hand_overrides"]}
    dialogues = {d["id"]: d for d in json.loads(DIALOGUES.read_text("utf-8"))["dialogues"]}
    report = json.loads(
        (PERF / "cycles-cp8/cycles-cp8_cache2048_gapall_r1.json").read_text("utf-8")
    )
    rows: list[dict[str, Any]] = []
    words: dict[str, list[str]] = {}
    answers: list[dict[str, Any]] = []
    for r in report["rows"]:
        if r["dialogue"] not in ("D1", "D5"):
            continue
        for a in r["answers"]:
            where = f"{r['dialogue']} seed {r['seed']}"
            hand = next(
                (o for o in data["answer_overrides"] if o["where"] == where and o["q"] == a["q"]),
                None,
            )
            answers.append({"where": where, "q": a["q"], "auto_pass": a["pass"], "hand_pass": hand["pass"] if hand else a["pass"],
                            "hand_reason": hand["reason"] if hand else None, "answer": a["answer"]})  # fmt: skip
        for c in r["cycles"]:
            where = f"{r['dialogue']} seed {r['seed']} v{c['cycle']}"
            words[where] = word_check(dialogues[r["dialogue"]], c["rendered"])
            rows += [
                score_one(x, where, c["rendered"], overrides)
                for x in claims.values()
                if x["dialogue"] == r["dialogue"]
            ]
    for name in data["rel002_runs"]:
        run = json.loads((PERF / name).read_text("utf-8"))
        for s in sorted(run["summaries"], key=lambda x: x["version"])[:2]:
            where = (
                f"{name.split('_')[2]} {name.split('_')[3].split('.')[0]} v{s['version']} (REL-002)"
            )
            rows += [
                score_one(claims[c], where, s["rendered"], overrides) for c in data["rel002_claims"]
            ]
    counts: dict[str, int] = {}
    for x in rows:
        counts[x["verdict"]] = counts.get(x["verdict"], 0) + 1
    per_claim: dict[str, dict[str, int]] = {}
    for x in rows:
        per_claim.setdefault(x["claim"], {}).setdefault(x["verdict"], 0)
        per_claim[x["claim"]][x["verdict"]] += 1
    summary = {
        "note": "Chosen to hold known losses: no general loss rate.",
        "checks": len(rows), "summaries": len({x["where"] for x in rows}), "verdicts": counts, "per_claim": per_claim,
        "rule_wrong": sum(1 for x in rows if x["override"]),
        "answers_auto_pass": sum(a["auto_pass"] for a in answers), "answers_hand_pass": sum(a["hand_pass"] for a in answers),
        "answers_total": len(answers),
    }  # fmt: skip
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {**summary, "rows": rows, "word_check_missing": words, "answers": answers},
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        "utf-8",
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "per_claim"}, ensure_ascii=False))
    for k, v in sorted(per_claim.items()):
        print(k, claims[k]["subject"], "/", claims[k]["value"], claims[k]["status"], v)
    seen: dict[tuple[str, str, str], list[str]] = {}
    for x in rows:
        seen.setdefault((x["claim"], x["rule"], x["line"] or ""), []).append(x["where"])
    print("--- distinct cases to read:", len(seen))
    for (c, v, line), where in sorted(seen.items()):
        print(c, v, f"x{len(where)}", "|", line[:150])


if __name__ == "__main__":
    main()
