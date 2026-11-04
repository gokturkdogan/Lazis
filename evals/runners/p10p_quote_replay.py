"""How much of what a summary lost is still in the verified quotes it stores? No model, no product change.

The stored content holds each item's quote, checked against the user's message, but the text shown to
the model in later turns leaves it out. This replays stored raw outputs: for each fact missing from the
rendered text, is it in the quote of a user item? It also estimates what showing the quotes would cost.
It says nothing about how the model would answer with them: that needs a model run.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from p3_context_eval import DATA
from p10p_compaction_cycles import FILLER_ROUNDS
from p10s_compaction_turn import SEED_A, SEED_Q

from lazis.conversation.compaction import normalize, parse_summary, verify_items

PERF = Path(__file__).resolve().parents[2] / "evals/reports/phase10/perf"
RUNS = {
    "limit 8, eski sıra, s3-v3 (50 özet)": ("cycles-cp8/cycles-cp8_cache2048_gapall_r1.json", "cycles-cp8/cycles-cp8_r1_progress/gapall.turns.jsonl"),
    "yeni sıra, s3-v4 (12 özet)": ("fix3-short/fix3-short_cache2048_gapshort_r1.json", "fix3-short/fix3-short_r1_progress/gapshort.turns.jsonl"),
    "yeni sıra + kural, s3-v5 (12 özet)": ("fix3b-short/fix3b-short_cache2048_gapshort_r1.json", "fix3b-short/fix3b-short_r1_progress/gapshort.turns.jsonl"),
}  # fmt: skip
LATE = PERF / "late-facts/late_cache2048_gaplate_r1.json"
LATE_WORDS = {
    "vegan": 2,
    "penisilin": 2,
    "fethiye": 2,
    "kesinleş": 3,
    "iptal": 3,
    "30 bin": 3,
    "hatırlat": 1,
}
OUT = PERF / "late-facts/quote_replay.json"


def filler() -> list[tuple[str, str]]:
    return [
        x
        for i in range(FILLER_ROUNDS)
        for x in (("user", SEED_Q[i % len(SEED_Q)]), ("assistant", SEED_A * 3))
    ]


def lookup(history: list[tuple[str, str]]) -> dict[int, Any]:
    return {
        i: SimpleNamespace(seq=i, role=r, content=c) for i, (r, c) in enumerate(history, start=1)
    }


def user_quotes(raw: str, history: list[tuple[str, str]], to_seq: int) -> list[str]:
    """Quotes of user items that pass the evidence check: a refused item is not in the summary."""
    clean, _, _ = verify_items(parse_summary(raw) or {}, lookup(history), covered_to=to_seq)
    return [
        str(i.get("quote") or "")
        for items in clean.values()
        for i in items
        if i.get("source") == "user"
    ]


def calls_by_version(path: Path) -> dict[tuple[str, int, int], dict[str, Any]]:
    out, last = {}, {}
    for line in path.read_text("utf-8").splitlines():
        row = json.loads(line)
        if "summary_call" in row:
            last = row["summary_call"]
        elif "i" in row and "cycle" in row:
            out[(row["dialogue"], row["seed"], row["cycle"])] = last
    return out


def main() -> None:
    result: dict[str, Any] = {}
    for name, (report, turns) in RUNS.items():
        data = json.loads((PERF / report).read_text("utf-8"))
        dialogues = {d["id"]: d for d in json.loads(DATA.read_text("utf-8"))["dialogues"]}
        calls = calls_by_version(PERF / turns)
        missing = recovered = 0
        cases: list[str] = []
        quote_chars = rendered_chars = 0
        for r in data["rows"]:
            history = [(m[0], m[1]) for m in dialogues[r["dialogue"]]["messages"]] + filler()
            for c in r["cycles"]:
                if c["cycle"] > 1:
                    history += filler()
                quotes = user_quotes(
                    calls[(r["dialogue"], r["seed"], c["cycle"])]["raw"], history, c["to_seq"]
                )
                text = normalize(" ".join(quotes))
                quote_chars += sum(len(q) for q in quotes)
                rendered_chars += len(c["rendered"])
                for w in c["missing"]:
                    missing += 1
                    if normalize(w) in text:
                        recovered += 1
                        cases.append(f"{r['dialogue']} s{r['seed']} v{c['cycle']} {w}")
        result[name] = {"missing": missing, "in_a_quote": recovered, "cases": cases,
                        "quote_chars_pct_of_rendered": round(100 * quote_chars / max(1, rendered_chars))}  # fmt: skip
    late = json.loads(LATE.read_text("utf-8"))
    phases = json.loads((DATA.parent / "tr_late_facts_v1.json").read_text("utf-8"))["phases"]
    rows: list[dict[str, Any]] = []
    by_seed = {7: late["summary_calls"][:4], 11: late["summary_calls"][4:8]}
    for r in late["rows"]:
        history: list[tuple[str, str]] = []
        for v, call, phase in zip(r["versions"], by_seed[r["seed"]], phases, strict=True):
            history += [(m[0], m[1]) for m in phase["messages"]] + filler()
            quotes = normalize(" ".join(user_quotes(call["raw"], history, v["to_seq"])))
            shown = normalize(v["rendered"])
            for word, start in LATE_WORDS.items():
                if v["stage"] >= start and normalize(word) not in shown:
                    rows.append(
                        {
                            "seed": r["seed"],
                            "stage": v["stage"],
                            "word": word,
                            "in_a_quote": normalize(word) in quotes,
                        }
                    )
    result["sonradan gelen bilgi (8 özet)"] = {
        "missing": len(rows),
        "in_a_quote": sum(x["in_a_quote"] for x in rows),
        "rows": rows,
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", "utf-8")
    for k, v in result.items():
        print(k, {a: b for a, b in v.items() if a != "rows"})
    print(result["sonradan gelen bilgi (8 özet)"]["rows"])


if __name__ == "__main__":
    main()
