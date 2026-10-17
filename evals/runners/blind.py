"""Blind pairwise rating of subjective Turkish answers (BENCHMARK_PLAN B5).

    # 1. build a local page from the saved quality outputs of the compared models
    uv run --project core python evals/runners/blind.py build --models qwen3.5:9b-q4_K_M gemma4:12b-it-qat ...
    # 2. open evals/reports/phase2/blind/rate.html in a browser, rate, press "Sonuçları indir"
    # 3. score the downloaded file
    uv run --project core python evals/runners/blind.py score ~/Downloads/lazis-blind-ratings.json

Model identities are never in the page: each pair is shown in random order and the mapping
lives only in key.json next to it. The page works offline, sends nothing anywhere and stores
nothing; ratings leave it only through the explicit download.
"""

from __future__ import annotations

import argparse
import html
import itertools
import json
import random
from collections import Counter
from pathlib import Path

from common import REPORTS, slug

OUT = REPORTS / "blind"


def build(models: list[str], seed: int, full: bool) -> None:
    outputs = {}
    for model in models:
        data = json.loads((REPORTS / slug(model) / "quality.json").read_text())
        outputs[model] = {i["id"]: i for i in data["quality"]["items"]}
    subjective = [i for i in outputs[models[0]].values() if i["subjective"]]
    dataset = json.loads((REPORTS.parents[1] / "datasets" / "tr_quality_v1.json").read_text())
    prompts = {i["id"]: i["prompt"] for i in dataset["items"]}
    pairs = list(itertools.combinations(models, 2))
    rng = random.Random(seed)
    tasks, key = [], []
    for n, item in enumerate(subjective):
        chosen = pairs if full else [pairs[n % len(pairs)]]
        for a, b in chosen:
            left, right = (a, b) if rng.random() < 0.5 else (b, a)
            tid = f"T{len(tasks) + 1:03d}"
            tasks.append({"id": tid, "item": item["id"], "prompt": prompts[item["id"]],
                          "left": outputs[left][item["id"]]["output"], "right": outputs[right][item["id"]]["output"]})
            key.append({"id": tid, "item": item["id"], "left": left, "right": right})
    rng.shuffle(tasks)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "key.json").write_text(json.dumps({"models": models, "seed": seed, "tasks": key}, ensure_ascii=False, indent=1))
    blocks = []
    for t in tasks:
        blocks.append(f"""<section data-id="{t['id']}"><h2>{t['id']} · {html.escape(t['prompt'])}</h2>
<div class="pair"><article><h3>Yanıt A</h3><p>{html.escape(t['left'])}</p></article>
<article><h3>Yanıt B</h3><p>{html.escape(t['right'])}</p></article></div>
<fieldset><label><input type="radio" name="{t['id']}" value="left"> A daha iyi</label>
<label><input type="radio" name="{t['id']}" value="tie"> Eşit</label>
<label><input type="radio" name="{t['id']}" value="right"> B daha iyi</label>
<input type="text" name="{t['id']}-note" placeholder="Not (isteğe bağlı)"></fieldset></section>""")
    page = f"""<!doctype html><html lang="tr"><meta charset="utf-8"><title>LAZIS kör değerlendirme</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>body{{font:15px/1.55 -apple-system,sans-serif;background:#0b1221;color:#e6edf8;max-width:1100px;margin:0 auto;padding:16px}}
section{{border:1px solid #2a3b5f;border-radius:12px;padding:12px 16px;margin:16px 0}}.pair{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
article{{background:#060a13;border-radius:10px;padding:10px 12px}}p{{white-space:pre-wrap}}h2{{font-size:15px}}h3{{font-size:13px;color:#8c9bb6;margin:0}}
fieldset{{border:0;display:flex;gap:16px;flex-wrap:wrap;padding:8px 0 0}}input[type=text]{{flex:1;min-width:200px;background:#0b1221;color:#e6edf8;border:1px solid #2a3b5f;border-radius:6px;padding:4px 8px}}
button{{padding:10px 18px;border-radius:10px;border:0;background:#3a7bff;color:#fff;font-size:15px}}@media(max-width:700px){{.pair{{grid-template-columns:1fr}}}}</style>
<h1>LAZIS — kör Türkçe değerlendirme</h1>
<p>Her soru için iki yanıt görüyorsunuz; hangi modelden geldikleri gizli ve sıraları rastgele. Doğallık, Türkçe kalitesi, sıcaklık, dürüstlük ve "efendim" hitabının doğallığına göre daha iyi olanı seçin. Bu sayfa hiçbir yere bir şey göndermez; bitince "Sonuçları indir" ile dosyayı kaydedin.</p>
{''.join(blocks)}
<button id="dl">Sonuçları indir</button>
<script>
document.getElementById("dl").onclick = () => {{
  const out = [];
  document.querySelectorAll("section").forEach(s => {{
    const id = s.dataset.id, c = s.querySelector('input[type=radio]:checked');
    out.push({{id, choice: c ? c.value : null, note: s.querySelector('input[type=text]').value}});
  }});
  const blob = new Blob([JSON.stringify({{ratings: out}}, null, 1)], {{type: "application/json"}});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "lazis-blind-ratings.json"; a.click();
}};
</script></html>"""
    (OUT / "rate.html").write_text(page)
    print(f"{len(tasks)} comparisons -> {OUT / 'rate.html'} (key: {OUT / 'key.json'})")


def score(ratings_path: Path) -> None:
    key = {t["id"]: t for t in json.loads((OUT / "key.json").read_text())["tasks"]}
    ratings = json.loads(ratings_path.read_text())["ratings"]
    wins: Counter[str] = Counter()
    games: Counter[str] = Counter()
    for r in ratings:
        if r["choice"] is None:
            continue
        t = key[r["id"]]
        games[t["left"]] += 1
        games[t["right"]] += 1
        if r["choice"] == "tie":
            wins[t["left"]] += 0.5  # type: ignore[assignment]
            wins[t["right"]] += 0.5  # type: ignore[assignment]
        else:
            wins[t[r["choice"]]] += 1
    result = {m: {"win_rate": round(wins[m] / games[m], 3), "comparisons": games[m]} for m in games}
    (OUT / "scores.json").write_text(json.dumps(result, indent=1))
    for m, v in sorted(result.items(), key=lambda kv: -kv[1]["win_rate"]):
        print(f"{m:28} win rate {v['win_rate']:.3f} over {v['comparisons']} comparisons")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--models", nargs="+", required=True)
    b.add_argument("--seed", type=int, default=20261017)
    b.add_argument("--full", action="store_true", help="every model pair for every item")
    s = sub.add_parser("score")
    s.add_argument("ratings", type=Path)
    args = ap.parse_args()
    if args.cmd == "build":
        build(args.models, args.seed, args.full)
    else:
        score(args.ratings)


if __name__ == "__main__":
    main()
