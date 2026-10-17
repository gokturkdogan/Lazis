"""Phase 2 Turkish quality evaluation (automatic checks; subjective items go to blind rating).

    uv run --project core python evals/runners/quality.py --model qwen3.5:9b-q4_K_M

Datasets (synthetic, versioned): evals/datasets/tr_quality_v1.json, tr_extraction_v1.json,
tr_long_conversation_v1.json. Fixed settings for every model: the Phase 2 system prompt for
assistant-style items, num_ctx 8192, think=false, seed 42, the model's own default sampling,
max 512 output tokens. Raw outputs are saved next to the scores.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

from common import REPO, manifest, summarize, write_report

from lazis.api.chat import PHASE2_SYSTEM_PROMPT
from lazis.errors import LlmError
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import (
    ChatMessage,
    ChatRequest,
    GenerationDone,
    GenerationMetrics,
    GenerationOptions,
    TextDelta,
)

DATA = REPO / "evals" / "datasets"
NUM_CTX = 8192
MAX_TOKENS = 512

EMOJI = re.compile("[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f000-\U0001f2ff⭐⭕]")
FOREIGN_SCRIPT = re.compile(r"[Ѐ-ӿ؀-ۿ぀-ヿ㐀-鿿가-힯]")
TR_WORDS = {"ve", "bir", "bu", "için", "ile", "de", "da", "çok", "ama", "gibi", "daha", "olarak",
            "ben", "sen", "siz", "size", "her", "mi", "mı", "ne", "var", "yok", "olan", "şey", "en"}
EN_WORDS = {"the", "and", "is", "are", "you", "to", "of", "in", "for", "with", "that", "this",
            "it", "be", "your", "can", "will", "have", "on", "as"}


def tr_lower(text: str) -> str:
    return text.replace("I", "ı").replace("İ", "i").lower()


def words(text: str) -> list[str]:
    return re.findall(r"[0-9A-Za-zÇĞİÖŞÜçğıöşüÂâÎîÛû'’:.-]+", text)


def is_turkish(text: str) -> bool:
    if FOREIGN_SCRIPT.search(text):
        return False
    toks = [tr_lower(w).strip(".,:;!?'’") for w in words(text)]
    if len(toks) < 4:  # one-word answers ("Can", "12:15") carry no language signal
        return True
    tr = sum(t in TR_WORDS for t in toks) + len(re.findall(r"[çğıöşüÇĞİÖŞÜ]", text)) / 3
    en = sum(t in EN_WORDS for t in toks)
    return tr >= en


def first_json(text: str) -> Any:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.M)
    try:
        return json.loads(cleaned)
    except ValueError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            return json.loads(match.group(0))
        except ValueError:
            return None
    return None


def numbers(text: str) -> list[float]:
    found = []
    for raw in re.findall(r"-?\d+(?:[.,]\d+)?", text.replace(" ", "")):
        try:
            found.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return found


def check(c: dict[str, Any], out: str) -> bool:
    low = tr_lower(out)
    kind, value = c["type"], c.get("value")
    if kind == "exact":
        return tr_lower(out.strip().strip('"').rstrip(".")).strip() == tr_lower(str(value)).rstrip(".")
    if kind == "contains_all":
        return all(any(tr_lower(a) in low for a in (v if isinstance(v, list) else [v])) for v in value)
    if kind == "contains_any":
        return any(tr_lower(v) in low for v in value)
    if kind == "not_contains":
        return not any(tr_lower(v) in low for v in value)
    if kind == "regex":
        return re.search(value, low) is not None
    if kind == "not_regex":
        return re.search(value, low) is None
    if kind == "json_equals":
        return first_json(out) == value
    if kind == "bullets":
        lines = [ln for ln in out.strip().splitlines() if ln.strip()]
        return len(lines) == value and all(ln.lstrip().startswith("- ") for ln in lines)
    if kind == "numbered":
        lines = [ln for ln in out.strip().splitlines() if ln.strip()]
        return [ln for ln in lines if re.match(r"^\s*\d+\.", ln)] == lines and len(lines) == value
    if kind == "max_words":
        return 0 < len(words(out)) <= value
    if kind == "uppercase":
        letters = [ch for ch in out if ch.isalpha()]
        return bool(letters) and out == out.replace("i", "İ").upper()
    if kind == "number":
        return any(abs(n - value) < 1e-6 for n in numbers(out))
    if kind == "no_emoji":
        return EMOJI.search(out) is None
    if kind == "turkish":
        return is_turkish(out)
    raise ValueError(kind)


async def generate(p: OllamaProvider, model: str, messages: list[ChatMessage], **kw: Any) -> tuple[str, GenerationMetrics | None, str | None]:
    opts = GenerationOptions(num_ctx=NUM_CTX, max_tokens=MAX_TOKENS, seed=42, think=False, **kw)
    text: list[str] = []
    metrics = None
    try:
        async for ev in p.stream(ChatRequest(model, messages, opts)):
            if isinstance(ev, TextDelta) and ev.kind == "content":
                text.append(ev.text)
            elif isinstance(ev, GenerationDone):
                metrics = ev.metrics
    except LlmError as exc:
        return "".join(text), metrics, exc.code
    return "".join(text), metrics, None


def person_scores(item: dict[str, Any], data: Any) -> dict[str, Any]:
    text = tr_lower(item["text"])
    preds = data.get("kisiler") if isinstance(data, dict) else None
    preds = [p for p in preds if isinstance(p, dict)] if isinstance(preds, list) else []
    pred_names = [tr_lower(str(p.get("ad", ""))).split()[0] if p.get("ad") else "" for p in preds]
    used: set[int] = set()
    matched = 0
    for gold in item["persons"]:
        for i, p in enumerate(preds):
            if i in used or pred_names[i] != tr_lower(gold["name"]):
                continue
            rel = tr_lower(str(p.get("iliski") or ""))
            if any(tr_lower(k) in rel for k in gold["rel"]):
                used.add(i)
                matched += 1
                break
    gold_names = {tr_lower(g["name"]) for g in item["persons"]}
    hallucinated = [n for n in pred_names if n and n not in text]
    spurious = [n for n in pred_names if n and n in text and n not in gold_names]
    forbidden = [n for n in pred_names if n in {tr_lower(x) for x in item["not_persons"]}]
    return {
        "person_recall": matched / len(item["persons"]) if item["persons"] else None,
        "name_recall": (len(gold_names & set(pred_names)) / len(gold_names)) if gold_names else None,
        "predicted_persons": len(preds),
        "hallucinated_names": hallucinated,
        "spurious_names": spurious,
        "corrected_away_names_extracted": forbidden,
    }


def field_recall(golds: list[list[str]], blob: str) -> float | None:
    if not golds:
        return None
    low = tr_lower(blob)
    return sum(any(tr_lower(v) in low for v in alts) for alts in golds) / len(golds)


def extraction_scores(item: dict[str, Any], out: str) -> dict[str, Any]:
    data = first_json(out)
    valid = isinstance(data, dict) and all(
        k in data for k in ("kisiler", "tarihler", "tercihler", "hedefler_projeler", "duzeltmeler")
    )
    result: dict[str, Any] = {"valid_json": isinstance(data, dict), "valid_schema": valid}
    if not isinstance(data, dict):
        return result
    dump = lambda key: json.dumps(data.get(key, []), ensure_ascii=False)  # noqa: E731
    result |= person_scores(item, data)
    result["date_recall"] = field_recall(item["dates"], dump("tarihler"))
    result["pref_recall"] = field_recall(item["prefs"], dump("tercihler"))
    result["goal_recall"] = field_recall(item["goals"], dump("hedefler_projeler"))
    result["correction_recall"] = field_recall(item["corrections"], dump("duzeltmeler"))
    return result


THINK_ITEMS = ("C01", "C02", "C03", "C04", "C05", "C06", "C07", "C08", "C09", "C10",
               "G01", "G02", "G09", "M02", "M08")


async def think_section(p: OllamaProvider, model: str) -> dict[str, Any]:
    """Reasoning items again with think=true (the 'long reasoning' profile)."""
    ds = {i["id"]: i for i in json.loads((DATA / "tr_quality_v1.json").read_text())["items"]}
    rows = []
    for item_id in THINK_ITEMS:
        item = ds[item_id]
        msgs = [ChatMessage("system", PHASE2_SYSTEM_PROMPT), ChatMessage("user", item["prompt"])]
        opts = GenerationOptions(num_ctx=NUM_CTX, max_tokens=4096, seed=42, think=True)
        text, thinking, metrics, err = [], [], None, None
        t0 = time.monotonic()
        try:
            async for ev in p.stream(ChatRequest(model, msgs, opts)):
                if isinstance(ev, TextDelta):
                    (thinking if ev.kind == "thinking" else text).append(ev.text)
                elif isinstance(ev, GenerationDone):
                    metrics = ev.metrics
        except LlmError as exc:
            err = exc.code
        out = "".join(text)
        rows.append({"id": item_id, "output": out, "error": err,
                     "passed": err is None and all(check(c, out) for c in item["checks"]),
                     "thinking_chars": len("".join(thinking)),
                     "output_tokens": metrics.output_tokens if metrics else None,
                     "wall_s": round(time.monotonic() - t0, 1)})
    return {"items": rows, "accuracy": round(sum(r["passed"] for r in rows) / len(rows), 3),
            "wall_s": summarize([r["wall_s"] for r in rows]),
            "output_tokens": summarize([r["output_tokens"] for r in rows])}


def rescore(report: dict[str, Any]) -> dict[str, Any]:
    """Recompute automatic checks on saved outputs (after a dataset check fix)."""
    ds = {i["id"]: i for i in json.loads((DATA / "tr_quality_v1.json").read_text())["items"]}
    for r in report["quality"]["items"]:
        item = ds[r["id"]]
        r["checks"] = [{"check": c, "passed": r["error"] is None and check(c, r["output"])} for c in item["checks"]]
        r["passed"] = all(c["passed"] for c in r["checks"]) if r["checks"] else None
        r["turkish"] = is_turkish(r["output"]) if r["output"] else False
    by_cat: dict[str, Any] = {}
    results = report["quality"]["items"]
    for cat in sorted({r["category"] for r in results}):
        scored = [r for r in results if r["category"] == cat and r["passed"] is not None]
        by_cat[cat] = {"scored": len(scored), "passed": sum(r["passed"] for r in scored),
                       "rate": round(sum(r["passed"] for r in scored) / len(scored), 3) if scored else None}
    report["quality"]["by_category"] = by_cat
    outs = [r for r in results if r["output"]]
    report["style"]["drift_rate"] = round(sum(not r["turkish"] for r in outs) / len(outs), 3)
    report["style"]["drift_items"] = [r["id"] for r in outs if not r["turkish"] and r["id"] != "B11"]
    if "think" in report:
        for row in report["think"]["items"]:
            row["passed"] = row["error"] is None and all(check(c, row["output"]) for c in ds[row["id"]]["checks"])
        rows = report["think"]["items"]
        report["think"]["accuracy"] = round(sum(r["passed"] for r in rows) / len(rows), 3)
    return report


async def evaluate(model: str) -> dict[str, Any]:
    p = OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=900)
    await p.load(model, num_ctx=NUM_CTX, keep_alive="30m")
    report: dict[str, Any] = {"manifest": manifest(model), "settings": {
        "num_ctx": NUM_CTX, "max_tokens": MAX_TOKENS, "think": False, "seed": 42,
        "sampling": "model defaults", "system_prompt": "PHASE2_SYSTEM_PROMPT (lazis.api.chat)"}}

    # 1. Quality items
    ds = json.loads((DATA / "tr_quality_v1.json").read_text())
    results = []
    for item in ds["items"]:
        msgs = [ChatMessage("system", PHASE2_SYSTEM_PROMPT)]
        msgs += [ChatMessage(h["role"], h["content"]) for h in item["history"]]
        msgs.append(ChatMessage("user", item["prompt"]))
        out, m, err = await generate(p, model, msgs)
        checks = [{"check": c, "passed": (err is None and check(c, out))} for c in item["checks"]]
        results.append({
            "id": item["id"], "category": item["category"], "subjective": item["subjective"],
            "output": out, "error": err,
            "passed": all(c["passed"] for c in checks) if checks else None,
            "checks": checks,
            "turkish": is_turkish(out) if out else False,
            "emoji": bool(EMOJI.search(out)),
            "efendim": len(re.findall(r"efendim", tr_lower(out))),
            "ttft_ms": m.ttft_ms if m else None, "decode_tps": m.decode_tps if m else None,
            "output_tokens": m.output_tokens if m else None,
        })
    by_cat: dict[str, Any] = {}
    for cat in sorted({r["category"] for r in results}):
        scored = [r for r in results if r["category"] == cat and r["passed"] is not None]
        by_cat[cat] = {"scored": len(scored), "passed": sum(r["passed"] for r in scored),
                       "rate": round(sum(r["passed"] for r in scored) / len(scored), 3) if scored else None}
    report["quality"] = {"by_category": by_cat, "items": results}

    # 2. Language and style across all quality outputs
    outs = [r for r in results if r["output"]]
    report["style"] = {
        "drift_rate": round(sum(not r["turkish"] for r in outs) / len(outs), 3),
        "drift_items": [r["id"] for r in outs if not r["turkish"] and r["id"] != "B11"],
        "emoji_rate": round(sum(r["emoji"] for r in outs) / len(outs), 3),
        "efendim_responses_rate": round(sum(r["efendim"] > 0 for r in outs) / len(outs), 3),
        "efendim_overuse_responses": [r["id"] for r in outs if r["efendim"] > 1],
        "errors": [r["id"] for r in results if r["error"]],
        "output_tokens": summarize([r["output_tokens"] for r in results if r["output_tokens"]]),
    }

    # 3. Structured extraction: free JSON vs schema-constrained
    ext = json.loads((DATA / "tr_extraction_v1.json").read_text())
    extraction: dict[str, Any] = {}
    for mode in ("prompt_only", "schema_constrained"):
        rows = []
        for item in ext["items"]:
            msgs = [ChatMessage("system", ext["instructions"]), ChatMessage("user", item["text"])]
            kw: dict[str, Any] = {"temperature": 0.0}
            if mode == "schema_constrained":
                kw["response_format"] = ext["schema"]
            out, _, err = await generate(p, model, msgs, **kw)
            rows.append({"id": item["id"], "output": out, "error": err, **extraction_scores(item, out)})
        def mean(key: str) -> float | None:
            vals = [r[key] for r in rows if r.get(key) is not None]
            return round(sum(vals) / len(vals), 3) if vals else None
        extraction[mode] = {
            "valid_json_rate": mean("valid_json"),
            "valid_schema_rate": mean("valid_schema"),
            "person_recall": mean("person_recall"),
            "name_recall": mean("name_recall"),
            "date_recall": mean("date_recall"),
            "pref_recall": mean("pref_recall"),
            "goal_recall": mean("goal_recall"),
            "correction_recall": mean("correction_recall"),
            "hallucinated_names": sum(len(r.get("hallucinated_names", [])) for r in rows),
            "spurious_names": sum(len(r.get("spurious_names", [])) for r in rows),
            "corrected_away_names_extracted": sum(len(r.get("corrected_away_names_extracted", [])) for r in rows),
            "rows": rows,
        }
    report["extraction"] = extraction

    # 4. Long conversation (append-only, the model's own replies kept)
    conv = json.loads((DATA / "tr_long_conversation_v1.json").read_text())
    history = [ChatMessage("system", PHASE2_SYSTEM_PROMPT)]
    turns = []
    for i, turn in enumerate(conv["turns"]):
        history.append(ChatMessage("user", turn["user"]))
        out, m, err = await generate(p, model, history)
        history.append(ChatMessage("assistant", out))
        checks = [check(c, out) for c in turn.get("checks", [])]
        turns.append({"turn": i + 1, "output": out, "error": err, "passed": all(checks) if checks else None,
                      "ttft_ms": m.ttft_ms if m else None})
    scored = [t for t in turns if t["passed"] is not None]
    report["long_conversation"] = {"recall_rate": round(sum(t["passed"] for t in scored) / len(scored), 3),
                                   "ttft_ms": summarize([t["ttft_ms"] for t in turns]), "turns": turns}
    report["think"] = await think_section(p, model)
    await p.aclose()
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--rescore", action="store_true", help="recompute checks on saved outputs")
    ap.add_argument("--add-think", action="store_true", help="run only the think=true section")
    args = ap.parse_args()
    t0 = time.monotonic()
    existing = REPO / "evals" / "reports" / "phase2" / args.model.replace(":", "_") / "quality.json"
    if args.rescore or args.add_think:
        report = json.loads(existing.read_text())
        if args.add_think:
            async def only_think() -> dict[str, Any]:
                p = OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=900)
                await p.load(args.model, num_ctx=NUM_CTX, keep_alive="30m")
                try:
                    return await think_section(p, args.model)
                finally:
                    await p.aclose()
            report["think"] = asyncio.run(only_think())
        report = rescore(report)
    else:
        report = asyncio.run(evaluate(args.model))
        report["duration_s"] = round(time.monotonic() - t0, 1)
    path = write_report(args.model, "quality", report)
    print(f"wrote {path} in {report['duration_s']} s")
    for cat, d in report["quality"]["by_category"].items():
        print(f"  {cat:12} {d['passed']}/{d['scored']}")
    print("  style:", {k: v for k, v in report["style"].items() if k != "output_tokens"})
    for mode, d in report["extraction"].items():
        print(f"  extraction {mode}: " + ", ".join(f"{k}={v}" for k, v in d.items() if k != "rows"))
    print("  long conversation recall:", report["long_conversation"]["recall_rate"])
    if "think" in report:
        print("  think=true reasoning accuracy:", report["think"]["accuracy"], "wall_s", report["think"]["wall_s"])


if __name__ == "__main__":
    main()
