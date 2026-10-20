"""Phase 7 relationship-graph performance on this machine (database side; no model).

    uv run --project core python evals/runners/p7_perf.py --scales 100,1000,10000,50000

For each scale a fresh throwaway encrypted database on disk is filled with a synthetic
graph: about one person per 4 relationships (plus organizations and projects), the user with
~150 direct relationships (family, friends, colleagues), "hub" people with many links, and a
known chain user → Ahmet Yılmaz (childhood friend) → Mehmet Yılmaz (sibling) → Elif Kaya
(spouse) → Can Kaya (sibling). Every measured query is the production code:

* direct: ``graph.neighbours`` of a random person / of the user;
* chains: ``graph.follow`` with 1, 2 and 3 steps from the user;
* paths: ``graph.paths_between`` (≤3 steps, meet in the middle) between random people;
* question: ``graph.ask`` (parse + name lookup + walk) for Turkish relationship questions;
* recall: ``retrieval.recall`` + ``render`` for a relationship question and a plain message;
* write: one relationship via ``relationships.apply_relations`` (resolution, policy, change
  set, evidence) — p50/p95 over 60 calls;
* map: ``graph.neighbourhood`` depth 2 from the user.

p50 / p95 / max over N runs; CPU, peak RSS, database size. Writes
evals/reports/phase7/perf_graph.json.
"""

from __future__ import annotations

import argparse
import json
import random
import resource
import secrets
import shutil
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from common import manifest

from lazis.config.model import StorageSection
from lazis.ids import utc_now_iso
from lazis.memory import graph, relations, retrieval
from lazis.memory import graphstore as gs
from lazis.memory import relationships as rels
from lazis.memory import repository as repo
from lazis.memory.models import USER_ID, EntityRef, RelCandidate
from lazis.memory.service import Source
from lazis.security.secrets import SecretBytes
from lazis.storage import open_storage
from lazis.storage.unit_of_work import UnitOfWork

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase7"

NAMES = ["Ahmet", "Mehmet", "Ayşe", "Zeynep", "Can", "Elif", "Burak", "Deniz", "Ece", "Kaan", "Selin",
         "Mert", "Derya", "Emre", "Gül", "Hakan", "İrem", "Oğuz", "Pınar", "Tolga"]  # fmt: skip
SURNAMES = ["Yıldız", "Aydın", "Öztürk", "Arslan", "Doğan", "Şahin", "Çelik", "Demir", "Koç", "Kurt"]
PERSON_TYPES = ["friend", "colleague", "neighbor", "cousin", "sibling", "business_partner", "acquaintance",
                "close_friend", "manager", "client", "teacher", "childhood_friend"]  # fmt: skip
USER_TYPES = ["friend", "colleague", "cousin", "neighbor", "close_friend", "business_partner", "childhood_friend"]
QUESTIONS = [
    "Çocukluk arkadaşım Ahmet Yılmaz'ın kardeşi kim?",
    "Çocukluk arkadaşım Ahmet Yılmaz'ın kardeşinin eşi kim?",
    "Çocukluk arkadaşım Ahmet Yılmaz'ın kardeşinin eşinin kardeşi kim?",
    "Can Kaya'yı nereden tanıyorum?",
    "Mehmet Yılmaz'ın kimlerle bağlantısı var?",
]
PLAIN = "Hafta sonu ne yapsam?"


def pct(values: list[float], p: float) -> float:
    values = sorted(values)
    return round(values[min(len(values) - 1, int(len(values) * p))], 2)


def stats(samples: list[float]) -> dict[str, float]:
    return {"p50": pct(samples, 0.5), "p95": pct(samples, 0.95), "max": round(max(samples), 2)}


def timed(fn: Callable[[], Any], n: int) -> list[float]:
    out: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t0) * 1000)
    return out


def seed(db: Any, n_rel: int, rng: random.Random) -> dict[str, Any]:
    """A synthetic graph with ``n_rel`` relationships. Returns ids of the known chain."""
    n_people = max(40, n_rel // 4)
    n_orgs = max(5, n_people // 20)
    n_projects = max(5, n_people // 25)
    now = utc_now_iso()

    def write(c: Any) -> dict[str, Any]:
        ids: dict[str, Any] = {}
        with UnitOfWork(c, kind="import", actor="system", summary="perf seed") as uow:
            people = []
            for i in range(n_people):
                name = f"{NAMES[i % len(NAMES)]} {SURNAMES[(i // len(NAMES)) % len(SURNAMES)]} {i}"
                people.append(repo.insert_entity(c, kind="person", name=name, relation=None, description=None, now=now).id)
            orgs = [repo.insert_entity(c, kind="organization", name=f"Kurum {i}", relation=None, description=None, now=now).id
                    for i in range(n_orgs)]  # fmt: skip
            projects = [repo.insert_entity(c, kind="project", name=f"Proje {i}", relation=None, description=None, now=now).id
                        for i in range(n_projects)]  # fmt: skip
            chain = {}
            for key, name in (("ahmet", "Ahmet Yılmaz"), ("mehmet", "Mehmet Yılmaz"), ("elif", "Elif Kaya"), ("can", "Can Kaya")):
                chain[key] = repo.insert_entity(c, kind="person", name=name, relation=None, description=None, now=now).id
            cs = uow.change_set_id

            def add(s: str, t: str, typ: str, status: str = "active") -> None:
                rt = relations.TYPES[typ]
                gs.insert_relationship(c, source_id=s, type=typ, target_id=t, qualifier=None, status=status,
                                       origin="stated", confidence=0.85, sensitivity=rt.sensitivity,
                                       sensitivity_category=rt.sensitivity_category, time_text=None,
                                       supersedes_id=None, change_set_id=cs, now=now)  # fmt: skip

            add(USER_ID, chain["ahmet"], "childhood_friend")
            add(chain["ahmet"], chain["mehmet"], "sibling")
            add(chain["mehmet"], chain["elif"], "spouse")
            add(chain["elif"], chain["can"], "sibling")
            made = 4
            user_links = min(150, n_rel // 10)
            for p in rng.sample(people, min(user_links, len(people))):
                add(USER_ID, p, rng.choice(USER_TYPES))
                made += 1
            hubs = people[: max(3, n_people // 100)]
            seen: set[tuple[str, str]] = set()
            while made < n_rel:
                r = rng.random()
                if r < 0.12:
                    add(rng.choice(people), rng.choice(orgs), "works_at", "ended" if rng.random() < 0.2 else "active")
                elif r < 0.2:
                    add(rng.choice(people), rng.choice(projects), "works_on")
                else:
                    a = rng.choice(hubs) if rng.random() < 0.15 else rng.choice(people)
                    b = rng.choice(people)
                    if a == b or (a, b) in seen:
                        continue
                    seen.add((a, b))
                    add(a, b, rng.choice(PERSON_TYPES), "ended" if rng.random() < 0.08 else "active")
                made += 1
            # The chain's people are ordinary: give them a few more links.
            for key in chain.values():
                for p in rng.sample(people, 5):
                    add(key, p, rng.choice(PERSON_TYPES))
            ids.update(chain=chain, people=people, hubs=hubs)
        return ids

    return db.run_sync(write)


def measure(n: int) -> dict[str, Any]:
    root = Path(tempfile.mkdtemp(prefix="lazis-p7perf-"))
    storage = open_storage(StorageSection(data_dir=root / "data"), SecretBytes(secrets.token_bytes(32)), app_version="perf")
    db = storage.db
    rng = random.Random(n)
    cpu0, wall0 = time.process_time(), time.perf_counter()
    ids = seed(db, n, rng)
    seed_s = time.perf_counter() - wall0
    seed_cpu = time.process_time() - cpu0
    stored = db.run_sync(gs.count_relationships)
    people: list[str] = ids["people"]
    chain = ids["chain"]
    reps = 200 if n <= 10000 else 100

    direct = timed(lambda: db.run_sync(lambda c: graph.neighbours(c, rng.choice(people))), reps)
    direct_hub = timed(lambda: db.run_sync(lambda c: graph.neighbours(c, rng.choice(ids["hubs"]))), reps)
    direct_user = timed(lambda: db.run_sync(lambda c: graph.neighbours(c, USER_ID)), reps)
    s1 = [graph.Step.of("childhood_friend")]
    s2 = [*s1, graph.Step.of("sibling")]
    s3 = [*s2, graph.Step.of("spouse")]
    one = timed(lambda: db.run_sync(lambda c: graph.follow(c, USER_ID, s1)), reps)
    two = timed(lambda: db.run_sync(lambda c: graph.follow(c, USER_ID, s2)), reps)
    three = timed(lambda: db.run_sync(lambda c: graph.follow(c, USER_ID, s3)), reps)
    friends3 = [graph.Step.of("friend"), graph.Step.of("friend"), graph.Step.of("colleague")]
    wide3 = timed(lambda: db.run_sync(lambda c: graph.follow(c, USER_ID, friends3)), max(20, reps // 4))
    paths = timed(lambda: db.run_sync(lambda c: graph.paths_between(c, rng.choice(people), rng.choice(people))), reps)
    paths_user = timed(lambda: db.run_sync(lambda c: graph.paths_between(c, USER_ID, chain["can"])), reps)
    ask: dict[str, Any] = {}
    answers: dict[str, Any] = {}
    for q in QUESTIONS:
        ask[q] = stats(timed(lambda q=q: db.run_sync(lambda c: graph.ask(c, q)), reps // 2))
        a = db.run_sync(lambda c, q=q: graph.ask(c, q))
        answers[q] = None if a is None else {"status": a.status, "lines": list(a.lines[:3])}
    budget = int(400 * 2.2)
    recall_rel = timed(lambda: retrieval.render(db.run_sync(lambda c: retrieval.recall(c, QUESTIONS[1], budget_chars=budget))), 60)
    recall_plain = timed(lambda: retrieval.render(db.run_sync(lambda c: retrieval.recall(c, PLAIN, budget_chars=budget))), 60)
    mapping = timed(lambda: db.run_sync(lambda c: graph.neighbourhood(c, USER_ID, depth=2)), 60)

    k = iter(range(10**9))

    def write() -> None:
        j = next(k)
        a, b = rng.sample(people, 2)
        ea, eb = (db.run_sync(lambda c, x=x: repo.get_entity(c, x)) for x in (a, b))
        assert ea is not None and eb is not None
        cand = RelCandidate(type="colleague", source=EntityRef(ea.name), target=EntityRef(eb.name),
                            quote=f"{ea.name} ile {eb.name} iş arkadaşı {j}")  # fmt: skip
        db.run_sync(lambda c: rels.apply_relations(c, [cand], source=Source("message", f"m{j}"), explicit=False))

    write_ms = timed(write, 60)
    db.run_sync(lambda c: c.execute("PRAGMA wal_checkpoint(TRUNCATE)"))
    files = [p for p in (root / "data").rglob("*") if p.is_file() and "backup" not in str(p)]
    size = sum(p.stat().st_size for p in files)
    storage.db.close()
    shutil.rmtree(root, ignore_errors=True)
    return {
        "relationships": n,
        "stored": stored,
        "people": len(people) + 4,
        "seed_s": round(seed_s, 2),
        "seed_cpu_s": round(seed_cpu, 2),
        "direct_ms": stats(direct),
        "direct_hub_ms": stats(direct_hub),
        "direct_user_ms": stats(direct_user),
        "chain1_ms": stats(one),
        "chain2_ms": stats(two),
        "chain3_ms": stats(three),
        "chain3_wide_ms": stats(wide3),
        "paths3_random_ms": stats(paths),
        "paths3_user_ms": stats(paths_user),
        "ask_ms": ask,
        "answers": answers,
        "recall_relationship_question_ms": stats(recall_rel),
        "recall_plain_ms": stats(recall_plain),
        "map_depth2_ms": stats(mapping),
        "write_ms": stats(write_ms),
        "db_bytes": size,
        "bytes_per_relationship": round(size / max(n, 1)),
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024, 1),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scales", default="100,1000,10000,50000")
    args = ap.parse_args()
    results = []
    for n in (int(x) for x in args.scales.split(",")):
        r = measure(n)
        brief = {k: r[k] for k in ("relationships", "people", "seed_s", "direct_ms", "direct_hub_ms", "chain2_ms",
                                   "chain3_ms", "chain3_wide_ms", "paths3_random_ms", "recall_relationship_question_ms",
                                   "write_ms", "db_bytes", "peak_rss_mb")}  # fmt: skip
        print(json.dumps(brief, ensure_ascii=False), flush=True)
        results.append(r)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "perf_graph.json"
    path.write_text(json.dumps({"manifest": manifest("gemma4:12b-it-qat"), "results": results}, ensure_ascii=False, indent=1) + "\n")
    print(path)


if __name__ == "__main__":
    main()
