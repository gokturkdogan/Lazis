"""Phase 6 memory performance on this machine (database side; no model).

    uv run --project core python evals/runners/p6_perf.py --scales 100,1000,10000,50000

For each scale a fresh throwaway encrypted database on disk is filled with synthetic records
(deterministic: users' facts, people, projects; about 1 entity per 8 records), then measured:

* write: one remembered fact = one ``apply_candidates`` call (policy, resolution,
  consolidation, change set, FTS) — p50/p95 over 60 calls;
* recall: ``retrieval.recall`` + ``render`` for realistic Turkish messages — p50/p95;
* entity matching: ``mentioned_entities`` for a message naming one person;
* search: FTS MATCH alone;
* CPU time, peak RSS of this process, database size (main file + WAL after a checkpoint).

Seeding uses batches of 200 records per change set (much faster than one by one; the
measured single write is separate). Writes evals/reports/phase6/perf_db.json.
"""

from __future__ import annotations

import argparse
import json
import random
import resource
import secrets
import shutil
import statistics
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from common import manifest

from lazis.config.model import StorageSection
from lazis.memory import retrieval, service, text
from lazis.memory import repository as repo
from lazis.memory.models import Candidate, EntityRef
from lazis.memory.orchestrator import mentioned_entities
from lazis.memory.service import Source
from lazis.security.secrets import SecretBytes
from lazis.storage import open_storage

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase6"

NAMES = ["Ahmet", "Mehmet", "Ayşe", "Zeynep", "Can", "Elif", "Burak", "Deniz", "Ece", "Kaan", "Selin",
         "Mert", "Derya", "Emre", "Gül", "Hakan", "İrem", "Oğuz", "Pınar", "Tolga"]  # fmt: skip
SURNAMES = ["Yılmaz", "Kaya", "Demir", "Şahin", "Çelik", "Yıldız", "Aydın", "Öztürk", "Arslan", "Doğan"]
RELATIONS = ["çocukluk arkadaşı", "iş arkadaşı", "kuzen", "komşu", "iş ortağı", "eski sınıf arkadaşı"]
JOBS = ["öğretmen", "mimar", "doktor", "avukat", "yazılımcı", "aşçı", "pilot", "grafiker", "muhasebeci"]
CITIES = ["İstanbul", "Ankara", "İzmir", "Bursa", "Antalya", "Eskişehir", "Trabzon", "Konya"]
HOBBIES = ["satranç", "dağcılık", "fotoğraf", "yüzme", "bisiklet", "gitar", "resim", "koşu", "yoga"]
TECH = ["Python", "Rust", "Go", "TypeScript", "Vue", "FastAPI", "PostgreSQL", "SQLite", "Docker"]
QUERIES = [
    "Bilgisayarımda büyük bir model çalışır mı?",
    "Ahmet Yılmaz'a doğum günü için ne alsam?",
    "Hafta sonu ne yapsam?",
    "Pusula projesinde hangi veritabanını seçmiştim?",
    "Nerede yaşıyorum?",
    "Merhaba, nasılsın?",
]


def synthetic(n: int, rng: random.Random) -> list[Candidate]:
    out: list[Candidate] = []
    for i in range(n):
        k = i % 8
        if k == 0:
            name = f"{rng.choice(NAMES)} {SURNAMES[(i // 8) % len(SURNAMES)]}{'' if i < 640 else ' ' + str(i // 640)}"
            rel = rng.choice(RELATIONS)
            job = rng.choice(JOBS)
            out.append(Candidate(predicate="occupation", value=job, statement=f"{name} {job}.", about="entity",
                                 entity=EntityRef(name, relation=rel), origin="imported"))  # fmt: skip
        elif k in (1, 2):
            h = rng.choice(HOBBIES)
            out.append(Candidate(predicate="interest", value=f"{h} {i}", statement=f"Kullanıcı {h} ile ilgileniyor ({i}).",
                                 origin="imported"))  # fmt: skip
        elif k == 3:
            c = rng.choice(CITIES)
            out.append(Candidate(predicate="event", value=f"{c} gezisi {i}", statement=f"Kullanıcı {c}'e gezi yaptı (kayıt {i}).",
                                 origin="imported"))  # fmt: skip
        elif k == 4:
            t = rng.choice(TECH)
            proj = f"Proje{i // 40}"
            out.append(Candidate(predicate="project_technology", value=f"{t}", statement=f"{proj} projesinde {t} kullanılıyor.",
                                 about="entity", entity=EntityRef(proj, kind="project"), origin="imported"))  # fmt: skip
        elif k == 5:
            out.append(Candidate(predicate="note", value=f"not {i}", statement=f"Kullanıcının notu: toplantı özeti {i}.",
                                 origin="imported"))  # fmt: skip
        elif k == 6:
            out.append(Candidate(predicate="goal", value=f"hedef {i}", statement=f"Kullanıcı {rng.choice(HOBBIES)} hedefi koydu ({i}).",
                                 origin="imported"))  # fmt: skip
        else:
            out.append(Candidate(predicate="likes", value=f"{rng.choice(HOBBIES)} {i}", statement=f"Kullanıcı {i} numaralı şeyi sever.",
                                 origin="imported"))  # fmt: skip
    return out


def pct(values: list[float], p: float) -> float:
    values = sorted(values)
    return round(values[min(len(values) - 1, int(len(values) * p))], 2)


def timed(fn: Callable[[], Any], n: int) -> list[float]:
    out = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000)
    return out


def measure(n: int) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="lazis-p6perf-"))
    storage = open_storage(StorageSection(data_dir=root / "data"), SecretBytes(secrets.token_bytes(32)), app_version="perf")
    db = storage.db
    rng = random.Random(n)
    cands = synthetic(n, rng)
    cpu0, wall0 = time.process_time(), time.perf_counter()
    for i in range(0, n, 200):
        batch = cands[i : i + 200]
        db.run_sync(lambda c, b=batch: service.apply_candidates(c, b, source=Source("import"), explicit=True, actor="import", kind="import"))
    seed_s = time.perf_counter() - wall0
    seed_cpu = time.process_time() - cpu0
    counts = db.run_sync(repo.count_memories)
    entities = len(db.run_sync(lambda c: repo.list_entities(c, limit=1_000_000)))

    k = iter(range(10**9))

    def write() -> None:
        j = next(k)
        c = Candidate(predicate="likes", value=f"yeni şey {j}", statement=f"Kullanıcı yeni şey {j} sever.")
        db.run_sync(lambda conn: service.apply_candidates(conn, [c], source=Source("message", f"m{j}"), explicit=False))

    write_ms = timed(write, 60)
    budget = int(400 * 2.2)
    recall_ms: dict[str, Any] = {}
    sizes: dict[str, int] = {}
    for q in QUERIES:
        samples = timed(lambda q=q: retrieval.render(db.run_sync(lambda c: retrieval.recall(c, q, budget_chars=budget))), 30)
        recall_ms[q] = {"p50": pct(samples, 0.5), "p95": pct(samples, 0.95)}
        r = db.run_sync(lambda c, q=q: retrieval.recall(c, q, budget_chars=budget))
        sizes[q] = len(r.items)
    all_recall = [v["p50"] for v in recall_ms.values()]
    entity_ms = timed(lambda: db.run_sync(lambda c: mentioned_entities(c, ["Ahmet Yılmaz bugün aradı"], limit=8)), 30)
    match = text.fts_match(text.query_terms("satranç gezisi"))
    assert match is not None
    search_ms = timed(lambda: db.run_sync(lambda c: repo.search(c, match, limit=24)), 30)
    db.run_sync(lambda c: c.execute("PRAGMA wal_checkpoint(TRUNCATE)"))
    files = [p for p in (root / "data").rglob("*") if p.is_file() and "backup" not in str(p)]
    size = sum(p.stat().st_size for p in files)
    storage.db.close()
    shutil.rmtree(root, ignore_errors=True)
    return {
        "records": n,
        "stored": counts,
        "entities": entities,
        "seed_s": round(seed_s, 2),
        "seed_cpu_s": round(seed_cpu, 2),
        "write_ms": {"p50": pct(write_ms, 0.5), "p95": pct(write_ms, 0.95)},
        "recall_ms_p50_median": round(statistics.median(all_recall), 2),
        "recall_ms_p95_max": max(v["p95"] for v in recall_ms.values()),
        "recall_ms": recall_ms,
        "recall_items": sizes,
        "entity_match_ms": {"p50": pct(entity_ms, 0.5), "p95": pct(entity_ms, 0.95)},
        "fts_search_ms": {"p50": pct(search_ms, 0.5), "p95": pct(search_ms, 0.95)},
        "db_bytes": size,
        "bytes_per_record": round(size / max(n, 1)),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scales", default="100,1000,10000,50000")
    args = ap.parse_args()
    results = []
    for n in (int(x) for x in args.scales.split(",")):
        r = measure(n)
        print(json.dumps({k: r[k] for k in ("records", "entities", "seed_s", "write_ms", "recall_ms_p50_median",
                                           "recall_ms_p95_max", "entity_match_ms", "fts_search_ms", "db_bytes",
                                           "peak_rss_mb")}, ensure_ascii=False), flush=True)  # fmt: skip
        results.append(r)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "perf_db.json"
    path.write_text(json.dumps({"manifest": manifest("gemma4:12b-it-qat"), "results": results}, ensure_ascii=False, indent=1) + "\n")
    print(path)


if __name__ == "__main__":
    main()
