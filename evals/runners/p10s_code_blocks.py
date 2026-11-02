"""Phase 10B stabilization: does fenced Python keep its meaning through the output guards?

    uv run --project core python evals/runners/p10s_code_blocks.py --model gemma4:12b-it-qat \
        --old-disclosure /path/to/old_disclosure.py --label <code>

Real Gemma, production engine and output length, throwaway profile, a new session per sample.
Per reply: the model's chunks exactly as Ollama sent them, the raw text, the shown reply. Fenced
Python is compared as text and by its syntax tree (``ast``):

* raw vs shown (the code under test, through the whole guard chain);
* with ``--old-disclosure``: the same recorded chunks through an earlier ``disclosure.py``, and
  the raw text in one piece and in fixed sizes through both versions (how the fault depends on
  chunking).

Writes evals/reports/phase10/code_blocks_<model>[_<label>].json.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import importlib.util
import json
import re
import sys
import textwrap
from collections.abc import AsyncIterator, Callable, Iterable
from pathlib import Path
from typing import Any

from common import manifest
from p6_sessions import Profile, Recorder
from p10b_adaptation import Full

from lazis.conversation import disclosure as new_disclosure
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import ChatRequest, StreamEvent, TextDelta

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase10"
FENCE = re.compile(r"^[ \t]*```(\w*)[ \t]*\n(.*?)^[ \t]*```", re.M | re.S)
SIZES = (1, 2, 3, 4, 5, 8, 16, 32, 10**6)

PROMPTS = [
    "Python'da bir listeyi ters çevirmenin üç yolunu kodla gösterir misin?",
    "Python'da bir sözlükteki değerleri döngüyle toplayan ve sonucu yazdıran kısa bir kod yazar mısın?",
    "İç içe iki for döngüsüyle çarpım tablosu yazdıran Python kodu yazar mısın?",
    "Python'da try/except/finally kullanan bir dosya okuma örneği gösterir misin?",
    "İçinde iki metot olan basit bir Python sınıfı yazar mısın?",
    "Python'da asal sayı bulan bir fonksiyon yaz, içinde if ve for iç içe olsun.",
    "Python'da 'with' kullanarak dosyaya yazan ve sonra okuyan iki ayrı örnek verir misin?",
    "Fibonacci dizisini hem özyinelemeli hem döngüyle hesaplayan iki Python fonksiyonu yazar mısın?",
    "Python'da bir decorator örneği gösterir misin, adım adım açıkla.",
    "Python'da liste kapsamı ile aynı işi yapan for döngüsünü karşılaştırır mısın?",
    "Bir metindeki kelimeleri sayan Python fonksiyonu yazıp numaralı adımlarla açıklar mısın?",
    "Python'da bir sistem komutu çalıştıran ve çıktısındaki bilgiyi yazdıran subprocess örneği verir misin?",
    "Python'da kabarcık sıralaması yazar mısın, döngü içinde koşul olsun.",
    "Python'da bir while döngüsüyle sayı tahmin oyunu yazar mısın?",
    "Python'da bir generator fonksiyonu ve onu kullanan bir for döngüsü gösterir misin?",
    "Python'da dataclass kullanan bir örnek ve onu işleyen bir fonksiyon yazar mısın?",
]


def python_blocks(text: str) -> list[str]:
    return [m.group(2) for m in FENCE.finditer(text) if m.group(1).lower() in ("python", "py", "python3")]


def tree(code: str) -> str | None:
    try:
        return ast.dump(ast.parse(textwrap.dedent(code)))
    except SyntaxError:
        return None


def compare(source: str, out: str) -> dict[str, int]:
    """Fenced Python of ``out`` against ``source``."""
    a, b = python_blocks(source), python_blocks(out)
    r = {"blocks": len(a), "parsable": 0, "text_differs": 0, "broken": 0, "meaning_changed": 0,
         "block_count_differs": int(len(a) != len(b))}  # fmt: skip
    for x, y in zip(a, b, strict=False):
        tx, ty = tree(x), tree(y)
        r["parsable"] += tx is not None
        r["text_differs"] += x != y
        if tx is not None and ty is None:
            r["broken"] += 1
        elif tx is not None and tx != ty:
            r["meaning_changed"] += 1
    return r


def through(module: Any, chunks: Iterable[str]) -> str:
    g = module.DisclosureGuard()
    return "".join(g.feed(c) for c in chunks) + g.finish()


class ChunkRecorder(Recorder):
    """Keeps the reply stream's chunks exactly as they came."""

    def __init__(self, inner: OllamaProvider) -> None:
        super().__init__(inner)
        self.chunks: list[str] = []

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        reply = request.options.response_format is None and request.options.max_tokens > 1
        if reply:
            self.chunks = []
        async for ev in super().stream(request):
            if reply and isinstance(ev, TextDelta) and ev.kind == "content" and ev.text:
                self.chunks.append(ev.text)
            yield ev


def load(path: str) -> Any:
    spec = importlib.util.spec_from_file_location("old_disclosure", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["old_disclosure"] = module
    spec.loader.exec_module(module)
    return module


def add(total: dict[str, int], part: dict[str, int]) -> None:
    for k, v in part.items():
        total[k] = total.get(k, 0) + v


async def main_async(model: str, samples: int, old: Any) -> dict[str, Any]:
    llm = ChunkRecorder(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200))
    p: Profile = Full(model, llm)
    rows: list[dict[str, Any]] = []
    try:
        await p.start()
        for k in range(samples):
            for q in PROMPTS:
                await p.clean_session()
                t = await p.say(q)
                raw, chunks, shown = "".join(llm.chunks), list(llm.chunks), t["reply"] or ""
                row: dict[str, Any] = {
                    "user": q, "sample": k, "raw": raw, "shown": shown, "chunks": chunks,
                    "chunk_chars_max": max(map(len, chunks), default=0),
                    "shown_vs_raw": compare(raw, shown),
                    "disclosure_new_real_chunks": compare(raw, through(new_disclosure, chunks)),
                }  # fmt: skip
                if old is not None:
                    row["disclosure_old_real_chunks"] = compare(raw, through(old, chunks))
                for size in SIZES:
                    cut: Callable[[str], list[str]] = lambda s, n=size: [
                        s[i : i + n] for i in range(0, len(s), n)
                    ]
                    row[f"new_{size}"] = compare(raw, through(new_disclosure, cut(raw)))
                    if old is not None:
                        row[f"old_{size}"] = compare(raw, through(old, cut(raw)))
                rows.append(row)
                print(json.dumps({"q": q[:50], "sample": k, "chunk_max": row["chunk_chars_max"],
                                  "shown": row["shown_vs_raw"],
                                  "old_real": row.get("disclosure_old_real_chunks")},
                                 ensure_ascii=False), flush=True)  # fmt: skip
    finally:
        await p.stop()
        p.remove()
        await llm.inner.aclose()
    keys = ["shown_vs_raw", "disclosure_new_real_chunks", "disclosure_old_real_chunks"]
    keys += [f"new_{s}" for s in SIZES] + [f"old_{s}" for s in SIZES]
    summary: dict[str, dict[str, int]] = {}
    for key in keys:
        total: dict[str, int] = {}
        for r in rows:
            if key in r:
                add(total, r[key])
        if total:
            summary[key] = total
    return {"model": model, "manifest": manifest(model), "summary": summary, "rows": rows}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--samples", type=int, default=2)
    ap.add_argument("--old-disclosure", default="")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    old = load(args.old_disclosure) if args.old_disclosure else None
    report = asyncio.run(main_async(args.model, args.samples, old))
    OUT.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[:/]", "_", args.model)
    path = OUT / f"code_blocks_{name}{'_' + args.label if args.label else ''}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=1), path)


if __name__ == "__main__":
    main()
