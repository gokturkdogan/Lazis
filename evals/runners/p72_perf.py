"""Phase 7.2: what the deterministic steps cost (no model; synthetic data).

    uv run --project core python evals/runners/p72_perf.py

* ``stated``: reading the user's words for namesakes, on ordinary messages (what every
  message pays) and on namesake messages;
* ``plan``: planning one message's candidates against a store of 1,000 people (100 of them
  namesakes of the planned name), entities and distinctions included;
* ``choice``: matching a short answer to an open "which X?" question;
* peak memory of each (tracemalloc).

The model-side timings (explicit request, ambiguity detection in chat, completing a waiting
record) are in the real-model reports (p72_identity, p71_perf). Writes
evals/reports/phase7_2/perf_offline.json.
"""

from __future__ import annotations

import json
import random
import secrets
import shutil
import statistics
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Any

from lazis.config.model import StorageSection
from lazis.ids import utc_now_iso
from lazis.memory import commands, namesakes, service
from lazis.memory import repository as memory_repo
from lazis.memory.extraction import ExtractedRel
from lazis.memory.models import Candidate, EntityRef, RelCandidate
from lazis.memory.service import Source
from lazis.security.secrets import SecretBytes
from lazis.storage import open_storage

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase7_2"
ORDINARY = [
    "Merhaba, bugün biraz plan yapmak istiyorum.", "Çocukluk arkadaşım Ahmet bu akşam bize gelecek.",
    "Hafta sonu için kısa bir gezi önerir misin?", "Bilgisayarımda 24 GB RAM var, yeter mi?",
    "Kahveyi şekersiz içerim, akşamları da hiç içmem.", "Ahmet'in kardeşi Mehmet, o da mühendis.",
    "Teşekkürler, şimdilik bu kadar.", "Projede Python ve Rust kullanıyorum.",
]  # fmt: skip
NAMESAKE = [
    "İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım.",
    "Üç Ayşe var hayatımda: kuzenim, komşum ve iş arkadaşım.",
    "İki Mehmet tanıyorum, biri öğretmen, diğeri mühendis.",
    "Ahmet hem komşum hem iş arkadaşım.",
]


def timed(fn: Any, n: int) -> dict[str, float]:
    samples = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1e6)
    samples.sort()
    return {"median_us": round(statistics.median(samples), 1),
            "p95_us": round(samples[int(len(samples) * 0.95)], 1), "max_us": round(samples[-1], 1)}  # fmt: skip


def peak(fn: Any) -> float:
    tracemalloc.start()
    fn()
    _, top = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return round(top / 1024, 1)


def main() -> None:
    out: dict[str, Any] = {}
    out["stated_ordinary"] = timed(lambda: [namesakes.stated(m) for m in ORDINARY], 300)
    out["stated_ordinary"]["messages"] = len(ORDINARY)
    out["stated_namesake"] = timed(lambda: [namesakes.stated(m) for m in NAMESAKE], 300)
    out["stated_namesake"]["messages"] = len(NAMESAKE)
    out["stated_peak_kib"] = peak(lambda: [namesakes.stated(m) for m in ORDINARY + NAMESAKE])

    root = Path(tempfile.mkdtemp(prefix="lazis-p72perf-"))
    storage = open_storage(StorageSection(data_dir=root / "data"), SecretBytes(secrets.token_bytes(32)),
                           app_version="eval")  # fmt: skip
    try:
        rng = random.Random(72)
        names = ["Ahmet", "Mehmet", "Ayşe", "Zeynep", "Can", "Elif", "Murat", "Selin", "Burak", "Deniz"]
        cands = [Candidate(predicate="occupation", value=f"meslek {i}", statement=f"Kişi {i}.",
                           about="entity", entity=EntityRef(f"{rng.choice(names)} {i}"))
                 for i in range(900)]  # fmt: skip
        cands += [Candidate(predicate="occupation", value=f"iş {i}", statement=f"Ahmet {i}.", about="entity",
                            entity=EntityRef("Ahmet", relation=f"tanıdık {i}")) for i in range(100)]  # fmt: skip
        for i in range(0, len(cands), 100):
            storage.db.run_sync(lambda c, b=cands[i : i + 100]: service.apply_candidates(
                c, b, source=Source("import"), explicit=True, actor="import", kind="import"))  # fmt: skip
        msg = "İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım."
        def rels(mid: str) -> list[ExtractedRel]:
            return [ExtractedRel(mid, RelCandidate(type="neighbor", target=EntityRef("Ahmet"), quote="biri komşum")),
                    ExtractedRel(mid, RelCandidate(type="colleague", target=EntityRef("Ahmet"),
                                                   quote="diğeri iş arkadaşım"))]  # fmt: skip

        samples = []
        for k in range(20):
            batch = rels(f"m{k}")
            t0 = time.perf_counter()
            storage.db.run_sync(lambda c, k=k, b=batch: namesakes.plan(c, msg, [], b, message_id=f"m{k}"))
            samples.append((time.perf_counter() - t0) * 1000)
        samples.sort()
        out["plan_1000_people"] = {"median_ms": round(statistics.median(samples), 2), "max_ms": round(samples[-1], 2)}
        out["plan_ordinary_message_ms"] = round(timed(lambda: storage.db.run_sync(
            lambda c: namesakes.plan(c, ORDINARY[1], [], [], message_id="x")), 50)["median_us"] / 1000, 3)  # fmt: skip

        # An open "which Ahmet?" question with two options, and short answers to it.
        ids = storage.db.run_sync(lambda c: [e.id for e in memory_repo.find_entities(c, "ahmet")][:2])
        item = type("Item", (), {"payload": {"options": [{"id": i, "label": "Ahmet"} for i in ids],
                                             "candidate": {"entity": {"name": "Ahmet"}}}})()  # fmt: skip
        out["choice"] = timed(lambda: storage.db.run_sync(lambda c: commands.choice_for(c, item, "Komşum olan.")), 200)
        out["now"] = utc_now_iso()
    finally:
        storage.db.close()
        shutil.rmtree(root, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "perf_offline.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(out, ensure_ascii=False), path)


if __name__ == "__main__":
    main()
