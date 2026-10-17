"""Aggregate perf.json + quality.json of every evaluated model into one comparison table.

    uv run --project core python evals/runners/compare.py

Writes evals/reports/phase2/comparison.json and prints a Markdown table. Numbers are copied
from the measurement files, never typed by hand.
"""

from __future__ import annotations

import json
from typing import Any

from common import REPORTS


def load(model_dir: str, name: str) -> dict[str, Any] | None:
    path = REPORTS / model_dir / f"{name}.json"
    return json.loads(path.read_text()) if path.exists() else None


def row(model_dir: str) -> dict[str, Any] | None:
    perf, quality = load(model_dir, "perf"), load(model_dir, "quality")
    if perf is None or quality is None:
        return None
    m = perf["manifest"]["model"]
    b2 = perf["b2_warm_latency"]["by_prompt_size"]
    cats = quality["quality"]["by_category"]
    ext = quality["extraction"]["prompt_only"]
    ext_s = quality["extraction"]["schema_constrained"]
    sweep = {s["num_ctx"]: s for s in perf["num_ctx_sweep"]}
    auto = [c for c in cats.values() if c["scored"]]
    return {
        "model": m["name"],
        "digest": m["digest"][:12],
        "size_gb": round(m["size_bytes"] / 1e9, 2),
        "quantization": m["details"].get("quantization_level"),
        "format": m["details"].get("format"),
        "runner": sweep[8192].get("runner"),
        "resident_gb_8k": sweep[8192]["ollama_size_gb"],
        "resident_gb_16k": sweep[16384]["ollama_size_gb"],
        "resident_gb_32k": sweep[32768]["ollama_size_gb"],
        "runner_idle_mb_16k": (perf["b4_memory"].get("precise_peak") or {}).get("idle_footprint_mb"),
        "runner_peak_mb_8k_prompt": (perf["b4_memory"].get("precise_peak") or {}).get("peak_footprint_mb"),
        "cold_load_ms_p50": perf["b1_cold_load"]["wall_ms"]["median"],
        "ttft_512_ms_p50": b2["512"]["ttft_ms"]["median"],
        "ttft_2k_ms_p50": b2["2048"]["ttft_ms"]["median"],
        "ttft_8k_ms_p50": b2["8192"]["ttft_ms"]["median"],
        "prefill_tps_2k": b2["2048"]["prefill_tps"]["median"],
        "decode_tps_2k": b2["2048"]["decode_tps"]["median"],
        "decode_tps_8k": b2["8192"]["decode_tps"]["median"],
        "multiturn_ttft_p50": perf["b3_multiturn_cache"]["ttft_ms_turns_2_10"]["median"],
        "multiturn_ttft_p95": perf["b3_multiturn_cache"]["ttft_ms_turns_2_10"]["p95"],
        "multiturn_reuse_p50": perf["b3_multiturn_cache"]["est_reuse_ratio_turns_2_10"]["median"],
        **{f"g2_warm_ttft_p50_{s['history_tokens_target'] // 1000}k": s["warm_ttft_ms"]["median"]
           for s in perf.get("g2_context", {}).get("sizes", [])},
        **{f"g2_cold_ttft_p50_{s['history_tokens_target'] // 1000}k": s["cold_ttft_ms"]["median"]
           for s in perf.get("g2_context", {}).get("sizes", [])},
        **{f"g2_warm_ttft_p50_{s['history_tokens_target'] // 1000}k_out256": s["warm_ttft_ms"]["median"]
           for s in perf.get("g2_context_out256", {}).get("sizes", [])},
        "num_ctx_change_reload_ms": perf["num_ctx_reload"]["changed_ctx_load_ms"],
        "long_context_needles": perf["long_context"]["accuracy"],
        "long_context_ttft_ms": round(sum(n["ttft_ms"] for n in perf["long_context"]["needles"]) / 3),
        "swap_growth_mb": round(perf["b4_memory"]["after_all"]["swap_used_mb"] - perf["b4_memory"]["before_b2"]["swap_used_mb"]),
        **{f"q_{k}": f"{v['passed']}/{v['scored']}" for k, v in cats.items() if v["scored"]},
        "q_auto_total": f"{sum(c['passed'] for c in auto)}/{sum(c['scored'] for c in auto)}",
        "think_accuracy": quality.get("think", {}).get("accuracy"),
        "think_wall_s_p50": quality.get("think", {}).get("wall_s", {}).get("median"),
        "drift_rate": quality["style"]["drift_rate"],
        "emoji_rate": quality["style"]["emoji_rate"],
        "efendim_rate": quality["style"]["efendim_responses_rate"],
        "efendim_overuse": len(quality["style"]["efendim_overuse_responses"]),
        "ext_valid_json": ext["valid_json_rate"],
        "ext_valid_json_schema": ext_s["valid_json_rate"],
        "ext_person_recall": ext["person_recall"],
        "ext_date_recall": ext["date_recall"],
        "ext_pref_recall": ext["pref_recall"],
        "ext_goal_recall": ext["goal_recall"],
        "ext_correction_recall": ext["correction_recall"],
        "ext_hallucinated": ext["hallucinated_names"] + ext["spurious_names"] + ext["corrected_away_names_extracted"],
        "long_conversation_recall": quality["long_conversation"]["recall_rate"],
        "errors": len(quality["style"]["errors"]),
        "power": perf["manifest"]["power"][0] if perf["manifest"]["power"] else "",
    }


def main() -> None:
    rows = [r for d in sorted(p.name for p in REPORTS.iterdir() if p.is_dir() and p.name != "blind") if (r := row(d))]
    (REPORTS / "comparison.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n")
    keys = list(rows[0].keys()) if rows else []
    print("| metric | " + " | ".join(r["model"] for r in rows) + " |")
    print("|---|" + "---|" * len(rows))
    for k in keys[1:]:
        print(f"| {k} | " + " | ".join(str(r.get(k)) for r in rows) + " |")


if __name__ == "__main__":
    main()
