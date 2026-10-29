"""What the output guards cost while a reply streams: the previous guard (Phase 7.1 claim guard
as of a6eb05d) against the current one (disclosure guard + claim guard), on the same real model
replies and their real chunk arrival times (recorded by p9_guards.py).

    uv run --project core python evals/runners/p9_guard_latency.py evals/reports/phase9/guards_gemma4_12b-it-qat.json

Each recorded reply is fed chunk by chunk at the times it arrived; a character counts as shown
when the guard releases it. Per reply: the delay of the first shown text after the first model
text, the mean and the worst delay of a character, and the guard's own compute time. The policy
is the turn's real claim state. Writes evals/reports/phase9/guard_latency_<model>.json.
"""

from __future__ import annotations

import importlib.util
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from lazis.conversation import disclosure
from lazis.conversation.reply_guard import ReplyGuard
from lazis.memory import claims

ROOT = Path(__file__).resolve().parents[2]
BEFORE = "a6eb05d"


def _old_claims() -> Any:
    src = subprocess.run(["git", "show", f"{BEFORE}:core/src/lazis/memory/claims.py"], cwd=ROOT,
                         check=True, capture_output=True, text=True).stdout  # fmt: skip
    path = Path(tempfile.mkdtemp()) / "claims_before.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("claims_before", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["claims_before"] = mod
    spec.loader.exec_module(mod)
    return mod


def replay(guard: Any, chunks: list[tuple[float, str]]) -> dict[str, Any]:
    arrival: list[float] = []  # per input character
    shown_at: list[float] = []  # per output character (the output may be shorter or longer)
    compute = 0.0
    for t, text in chunks:
        arrival += [t] * len(text)
        c0 = time.perf_counter()
        out = guard.feed(text)
        compute += time.perf_counter() - c0
        shown_at += [t] * len(out)
    end = chunks[-1][0] if chunks else 0.0
    c0 = time.perf_counter()
    out = guard.finish()
    compute += time.perf_counter() - c0
    shown_at += [end] * len(out)
    n = min(len(arrival), len(shown_at))
    delays = [shown_at[i] - arrival[i] for i in range(n)]
    first = next((t for t, s in zip(shown_at, guard.released, strict=False) if s.strip()), end)
    first_in = next((t for t, text in chunks if text.strip()), 0.0)
    return {
        "first_shown_delay_s": round(first - first_in, 4),
        "mean_char_delay_s": round(statistics.fmean(delays), 4) if delays else 0.0,
        "max_char_delay_s": round(max(delays), 4) if delays else 0.0,
        "compute_ms": round(compute * 1000, 3),
        "text": guard.released,
    }


def main() -> None:
    report = json.loads(Path(sys.argv[1]).read_text())
    old = _old_claims()
    rows = []
    for conv in report["conversations"]:
        for t in conv["turns"]:
            if t["scripted"] or not t["raw_chunks"] or t["end"] != "done":
                continue
            state = t["claim_state"] or "no_memory_action"
            memory_turn = t["request"] not in (None, "recall", "secret")
            recalled = False  # the replay cannot know; references are not timed differently
            before = replay(old.ClaimGuard(old.Policy(old.ClaimState(state), recalled, memory_turn)), t["raw_chunks"])
            now = claims.Policy(claims.ClaimState(state), recalled, memory_turn,
                                claims.memory_talk(t["user"]), claims.explaining(t["user"]))  # fmt: skip
            after = replay(ReplyGuard(now, disclosure.asks_instructions(t["user"])), t["raw_chunks"])
            rows.append({"cid": conv["cid"], "group": conv["group"], "before": before, "after": after,
                         "text_changed": before["text"] != after["text"]})  # fmt: skip

    def agg(key: str, side: str) -> dict[str, float]:
        xs = sorted(r[side][key] for r in rows)
        return {"median": round(statistics.median(xs), 4), "p90": round(xs[int(0.9 * (len(xs) - 1))], 4),
                "max": round(xs[-1], 4)}  # fmt: skip

    summary = {"replies": len(rows)}
    for key in ("first_shown_delay_s", "mean_char_delay_s", "max_char_delay_s", "compute_ms"):
        summary[key] = {"before": agg(key, "before"), "after": agg(key, "after")}
    summary["replies_whose_text_differs"] = sum(r["text_changed"] for r in rows)
    out = {"source": sys.argv[1], "before": BEFORE, "summary": summary, "rows": rows}
    name = Path(sys.argv[1]).stem.replace("guards_", "guard_latency_")
    path = Path(sys.argv[1]).parent / f"{name}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=1), path)


if __name__ == "__main__":
    main()
