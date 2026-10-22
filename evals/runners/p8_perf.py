"""Phase 8 performance on this machine: profiles of 20, 100 and 500 facts (synthetic data only).

    uv run --project core python evals/runners/p8_perf.py --model gemma4:12b-it-qat
    uv run --project core python evals/runners/p8_perf.py --model gemma4:12b-it-qat --sizes 20,100 --formats json

For each size, a JSON profile (mapped without the model) and a Markdown profile (read by the
model, one call per section), each on its own throwaway encrypted profile: analysis time, model
calls, failed sections, the preview (people, items, summary, per-item checks), every item
decided one by one (as the UI does), the write (one transaction), the undo plan and the undo.
Memory: the Python heap peak (tracemalloc), the backend process's peak RSS, and the model
runner's footprint. Writes evals/reports/phase8/perf_<model>.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import resource
import time
import tracemalloc
from pathlib import Path
from typing import Any

from common import footprint_mb, manifest, runner_pids
from p6_sessions import Profile, Recorder

from lazis.bootstrap import apply, files, pipeline, store, undo
from lazis.providers.llm.ollama import OllamaProvider

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase8"
NAMES = ["Aras", "Bora", "Ceren", "Defne", "Emre", "Funda", "Gökhan", "Hale", "Irmak", "Kaan", "Lale",
         "Mert", "Nil", "Onur", "Pelin", "Rüzgar", "Selin", "Tuna", "Umut", "Vera", "Yiğit", "Zehra"]  # fmt: skip
SURNAMES = ["Akın", "Bulut", "Çelik", "Demir", "Ekinci", "Fidan", "Güneş", "Hazar", "Işık", "Kaya"]
RELS = ["kuzenim", "arkadaşım", "komşum", "iş arkadaşım", "eski iş arkadaşım", "çocukluk arkadaşım"]
JOBS = ["mimar", "öğretmen", "hemşire", "avukat", "aşçı", "pilot", "eczacı", "veteriner", "editör",
        "mühendis", "fotoğrafçı", "muhasebeci"]  # fmt: skip
CITIES = ["Bursa", "Eskişehir", "Trabzon", "Konya", "Muğla", "Edirne", "Rize", "Kars", "Sinop", "Bolu",
          "Artvin", "Aydın", "Çorum", "Tokat"]  # fmt: skip
HOBBIES = ["satranç", "yüzme", "seramik", "tırmanış", "dalış", "okçuluk", "kayak", "yelken", "tenis",
           "bisiklet", "keman", "resim", "yoga", "kampçılık"]  # fmt: skip


def people_needed(n: int) -> int:
    return max(1, (n - 8 + 3) // 4)


def person(i: int) -> tuple[str, str]:
    return f"{NAMES[i % len(NAMES)]} {SURNAMES[(i // len(NAMES)) % len(SURNAMES)]}", RELS[i % len(RELS)]


def markdown(n: int) -> str:
    """~n facts: 8 about the user, then people with 4 facts each (job, city, two hobbies)."""
    out = ["# Hakkımda", "Meslek: veri analisti", "Şehir: İzmir", "İşyeri: Kervan Lojistik",
           "Diller: Türkçe ve İngilizce", "Bilgisayar: MacBook Pro", "Filtre kahveyi severim.",
           "Her sabah koşarım.", "", "# Tanıdıklarım"]  # fmt: skip
    for i in range(people_needed(n)):
        name, rel = person(i)
        out += [f"## {name}", f"{rel.capitalize()}. Mesleği {JOBS[i % len(JOBS)]}. "
                f"{CITIES[i % len(CITIES)]}'da yaşıyor. {HOBBIES[i % len(HOBBIES)]} ve "
                f"{HOBBIES[(i + 5) % len(HOBBIES)]} ile ilgileniyor.", ""]  # fmt: skip
    return "\n".join(out)


def json_profile(n: int) -> str:
    ppl = []
    for i in range(people_needed(n)):
        name, rel = person(i)
        ppl.append({"id": f"p{i}", "name": name, "relation": rel,
                    "facts": {"occupation": JOBS[i % len(JOBS)], "location": CITIES[i % len(CITIES)],
                              "interest": [HOBBIES[i % len(HOBBIES)], HOBBIES[(i + 5) % len(HOBBIES)]]}})  # fmt: skip
    doc = {"schema_version": "1.0",
           "profile": {"occupation": "veri analisti", "city": "İzmir", "employer": "Kervan Lojistik",
                       "languages": ["Türkçe", "İngilizce"], "computer": "MacBook Pro"},
           "preferences": ["filtre kahve"], "habits": ["her sabah koşarım"], "people": ppl}  # fmt: skip
    return json.dumps(doc, ensure_ascii=False, indent=1)


def rss_mb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1)  # bytes on macOS


async def one(model: str, llm: Recorder, size: int, fmt: str) -> dict[str, Any]:
    p = Profile(model, llm)
    await p.start()
    assert p.engine is not None
    runner_peak = 0.0
    try:
        raw = json_profile(size) if fmt == "json" else markdown(size)
        name = "profil.json" if fmt == "json" else "profil.md"
        tracemalloc.start()
        t0 = time.monotonic()
        f = files.read(name, raw.encode())
        if fmt == "json":
            iid = p.q(lambda c: pipeline.start_json(c, f))
        else:
            iid = p.q(lambda c: store.create_batch(c, f, model=model))
            p.engine.bootstrap.start(iid)
            while p.q(lambda c: store.get_batch(c, iid)).status == "analyzing":
                for pid in runner_pids():
                    runner_peak = max(runner_peak, footprint_mb(pid) or 0.0)
                await asyncio.sleep(0.5)
        analysis_s = time.monotonic() - t0
        b = p.q(lambda c: store.get_batch(c, iid))

        def preview(c: Any) -> int:
            ps, its = store.people(c, iid), store.items(c, iid)
            store.summary(c, iid)
            for it in its:
                store.blocked(c, iid, it)
            return len(ps) + len(its)

        t1 = time.monotonic()
        shown = p.q(preview)
        preview_s = time.monotonic() - t1

        t2 = time.monotonic()
        for person_ in p.q(lambda c: store.people(c, iid)):
            p.q(lambda c, x=person_: store.decide_person(c, iid, x.id, "create"))
        for it in p.q(lambda c: store.items(c, iid)):
            if it.classification == "excluded":
                continue
            res = "update" if it.classification in store.NEEDS_RESOLUTION else None
            p.q(lambda c, x=it, r=res: store.decide_item(c, iid, x.id, "approve", resolution=r))  # type: ignore[arg-type]
        decide_s = time.monotonic() - t2

        t3 = time.monotonic()
        r = p.q(lambda c: apply.apply(c, iid))
        apply_s = time.monotonic() - t3
        t4 = time.monotonic()
        plan = p.q(lambda c: undo.plan(c, iid))
        plan_s = time.monotonic() - t4
        t5 = time.monotonic()
        p.q(lambda c: undo.undo(c, iid))
        undo_s = time.monotonic() - t5
        _, heap = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        items = len(p.q(lambda c: store.items(c, iid)))
        return {
            "size": size, "format": fmt, "bytes": len(raw.encode()), "status": b.status,
            "sections": b.sections_total, "sections_failed": b.sections_failed,
            "model_calls": b.model_calls, "items": items, "shown": shown,
            "written": r.counts["written"], "people_created": r.counts["people_created"],
            "undo_steps": len(plan.steps),
            "analysis_s": round(analysis_s, 2), "preview_s": round(preview_s, 3),
            "decide_all_s": round(decide_s, 2), "apply_s": round(apply_s, 3),
            "undo_plan_s": round(plan_s, 3), "undo_s": round(undo_s, 3),
            "python_heap_peak_mb": round(heap / 2**20, 1), "process_rss_peak_mb": rss_mb(),
            "model_runner_footprint_peak_mb": runner_peak or None,
        }  # fmt: skip
    finally:
        await p.stop()
        p.remove()


async def turn_latency(p: Profile, message: str) -> dict[str, float | None]:
    """Time to the first visible token and to the end of one chat turn."""
    import secrets

    from lazis.conversation import TurnRequest

    assert p.engine is not None
    t0 = time.monotonic()
    first = None
    handle = await p.engine.begin_turn(TurnRequest(p.session_id, f"perf-{secrets.token_hex(6)}", message, p.model))
    async for e in p.engine.events(handle):
        if e["type"] == "delta" and first is None:
            first = time.monotonic() - t0
    return {"ttft_s": None if first is None else round(first, 2), "total_s": round(time.monotonic() - t0, 2)}


async def chat_during_import(model: str, llm: Recorder) -> dict[str, Any]:
    """A user turn while the model is reading a profile: the import yields (it is preempted and
    carries on afterwards). Compared with the same turn when nothing runs."""
    p = Profile(model, llm)
    await p.start()
    assert p.engine is not None
    try:
        await p.clean_session()
        def say(stage: str) -> None:
            print(f"   chat_during_import: {stage} {time.strftime('%H:%M:%S')}", flush=True)

        say("warm")
        await asyncio.wait_for(turn_latency(p, "Merhaba."), 300)
        idle = await asyncio.wait_for(
            turn_latency(p, "Bugün kısa bir yürüyüş yapmayı düşünüyorum, ne dersin?"), 300)
        say("idle turn done")
        f = files.read("profil.md", markdown(100).encode())
        iid = p.q(lambda c: store.create_batch(c, f, model=model))
        p.engine.bootstrap.start(iid)
        started = time.monotonic()
        while p.engine.scheduler.background is None and time.monotonic() - started < 120:
            await asyncio.sleep(0.1)
        say(f"import job running={p.engine.scheduler.background is not None}")
        await asyncio.sleep(1.0)  # the model is in the middle of a section
        busy = await asyncio.wait_for(turn_latency(p, "Akşam için hafif bir yemek önerir misin?"), 300)
        say("busy turn done")
        started = time.monotonic()
        while (p.q(lambda c: store.get_batch(c, iid)).status == "analyzing"
               and time.monotonic() - started < 1200):
            await asyncio.sleep(0.5)
        say("import finished")
        b = p.q(lambda c: store.get_batch(c, iid))
        return {"idle_turn": idle, "turn_during_import": busy, "import_status_after": b.status,
                "import_sections": b.sections_total, "import_sections_failed": b.sections_failed}
    finally:
        await p.stop()
        p.remove()


async def chat_only(model: str) -> dict[str, Any]:
    llm = Recorder(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1800))
    try:
        return await chat_during_import(model, llm)
    finally:
        await llm.inner.aclose()


async def run(model: str, sizes: list[int], formats: list[str]) -> dict[str, Any]:
    llm = Recorder(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1800))
    rows = []
    for fmt in formats:
        for n in sizes:
            row = await one(model, llm, n, fmt)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            rows.append(row)
    chat = await chat_during_import(model, llm) if "markdown" in formats else None
    print(json.dumps(chat, ensure_ascii=False), flush=True)
    await llm.inner.aclose()
    return {"model": model, "manifest": manifest(model), "rows": rows, "chat_during_import": chat}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:12b-it-qat")
    ap.add_argument("--sizes", default="20,100,500")
    ap.add_argument("--formats", default="json,markdown")
    ap.add_argument("--chat-only", action="store_true")
    args = ap.parse_args()
    if args.chat_only:
        chat = asyncio.run(chat_only(args.model))
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"perf_chat_{re.sub(r'[:/]', '_', args.model)}.json").write_text(
            json.dumps({"model": args.model, "manifest": manifest(args.model), "chat_during_import": chat},
                       ensure_ascii=False, indent=1) + "\n")
        print(json.dumps(chat, ensure_ascii=False))
        return
    sizes = [int(x) for x in args.sizes.split(",")]
    formats = [x.strip() for x in args.formats.split(",")]
    report = asyncio.run(run(args.model, sizes, formats))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"perf_{re.sub(r'[:/]', '_', args.model)}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(path)


if __name__ == "__main__":
    main()
