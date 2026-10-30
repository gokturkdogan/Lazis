"""What the Phase 9.1 steps cost (no model): the request scope (per learned message and per
turn), "kaydettin mi?" detection, the field check (per proposed item) and the forget target on a
profile with 500 records. Synthetic data, a throwaway encrypted database.

    uv run --project core python evals/runners/p91_overhead.py

Writes evals/reports/phase9/memory_ops_overhead.json.
"""

from __future__ import annotations

import json
import secrets
import shutil
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from lazis.config.model import StorageSection
from lazis.memory import commands, extraction, service
from lazis.memory.models import Candidate
from lazis.memory.service import Source
from lazis.security.secrets import SecretBytes
from lazis.storage import open_storage

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase9"
REPORTS = sorted((OUT).glob("guards_*.json"))


def messages() -> list[str]:
    seen: list[str] = []
    for p in REPORTS:
        for c in json.loads(p.read_text())["conversations"]:
            for t in c["turns"]:
                if t["user"] not in seen:
                    seen.append(t["user"])
    return seen


def per_call_us(fn: Any, args: list[Any], rounds: int = 20) -> dict[str, float]:
    times = []
    for _ in range(rounds):
        for a in args:
            start = time.perf_counter_ns()
            fn(a)
            times.append((time.perf_counter_ns() - start) / 1000)
    times.sort()
    return {"median_us": round(statistics.median(times), 1), "p99_us": round(times[int(len(times) * 0.99)], 1),
            "max_us": round(times[-1], 1), "calls": len(times)}  # fmt: skip


def main() -> None:
    msgs = messages()
    item = {"message": "m1", "quote": "Kız kardeşim Ece Bursa'da yaşıyor.", "entity": "Ece", "relation": "",
            "predicate": "family", "value": "Bursa'da yaşıyor", "statement": "Ece Bursa'da yaşıyor.", "change": False,
            "replaces": "", "certain": True, "sensitive": "", "importance": 0.8}  # fmt: skip
    target = [extraction.Target("m1", "x", "Kız kardeşim Ece Bursa'da yaşıyor.")]
    report: dict[str, Any] = {
        "messages": len(msgs),
        "learnable_part": per_call_us(commands.learnable_part, msgs),
        "asks_if_saved": per_call_us(commands.asks_if_saved, msgs),
        "fit_field": per_call_us(
            lambda _: extraction.fit_field(
                "family",
                "Bursa'da yaşıyor",
                item["quote"],
                item["statement"],
                about_person=True,
                name="Ece",
            ),
            list(range(200)),
        ),  # fmt: skip
        "validate_one_item": per_call_us(
            lambda _: extraction.validate([item], target), list(range(200))
        ),
    }
    root = Path(tempfile.mkdtemp(prefix="lazis-p91o-"))
    try:
        st = open_storage(
            StorageSection(data_dir=root / "data"),
            SecretBytes(secrets.token_bytes(32)),
            app_version="eval",
        )
        cands = [
            Candidate(predicate="likes", value=f"şey {i}", statement=f"Kullanıcı şey {i} sever.")
            for i in range(497)
        ]
        cands += [Candidate(predicate="habit", value="şekersiz kahve", statement="Kullanıcı kahveyi şekersiz içer."),
                  Candidate(predicate="phone", value="Pixel 8", statement="Kullanıcının telefonu Pixel 8."),
                  Candidate(predicate="location", value="İstanbul", statement="Kullanıcı İstanbul'da yaşıyor.")]  # fmt: skip
        st.db.run_sync(
            lambda c: service.apply_candidates(c, cands, source=Source("import"), explicit=True)
        )
        forget = ["Kahve bilgimi sil.", "Telefon bilgimi unut.", "İstanbul'da yaşadığım bilgisini unut.",
                  "Araba bilgimi sil."]  # fmt: skip
        report["forget_target_500_records"] = per_call_us(
            lambda m: st.db.run_sync(lambda c: commands.forget_target(c, m, None)),
            forget,
            rounds=10,
        )
        st.db.close()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "memory_ops_overhead.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=1), path)


if __name__ == "__main__":
    main()
