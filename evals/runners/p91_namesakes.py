"""Phase 9.1 with the real model: namesakes — a fact goes to the one the user's words name, or to
none (production engine, synthetic data, throwaway encrypted profiles).

    uv run --project core python evals/runners/p91_namesakes.py --model gemma4:12b-it-qat

Two paths, every scenario three times (three generations of the model):

* ``file`` — a profile file through the Phase 8 import (the scenario machinery of
  ``p8_bootstrap.py``: analysis, the simulated user creating every person, apply, the database
  read afterwards). A job or city counts as written to the wrong person in any field
  (occupation, note, family, location), not only the expected one.
* ``chat`` — the same sentences said in chat, background learning settled after every turn,
  the database read (people with their relation words, facts, open "which one?" questions).

Safety (must hold in every run): no fact on a namesake the user's words do not name, no more
people of the name than the user counted, nothing said of "Ahmet" alone written to either.
Recall (reported, not required): every expected fact written.
Writes evals/reports/phase9/namesakes_<model>[_<label>].json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import p8_bootstrap as boot
from common import manifest
from p6_sessions import Profile
from p9_guards import T, GuardRecorder, say

from lazis.memory import claims, text
from lazis.memory import repository as memory_repo
from lazis.providers.llm.ollama import OllamaProvider

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase9"
REPEATS = 3
JOB = "occupation|note|family"
CITY = "location|note|family"


@dataclass
class Case:
    id: str
    messages: list[str]  # chat: one per turn; file: joined by blank lines
    name: str
    count: int  # people of the name the user said there are
    expect: list[tuple[str, str, str]]  # (relation word, predicates, value part)
    forbid: list[str] = field(default_factory=list)  # value parts written to nobody of the name
    file: bool = True  # also as a profile file


CASES = [
    Case("j1", ["İki Ahmet tanıyorum. Biri komşum, mimar. Diğeri iş arkadaşım, muhasebeci."], "Ahmet", 2,
         [("komşu", JOB, "mimar"), ("iş arkadaş", JOB, "muhasebeci")]),
    Case("j2", ["İki Ahmet var: biri komşum ve mimar, diğeri iş arkadaşım ve muhasebeci."], "Ahmet", 2,
         [("komşu", JOB, "mimar"), ("iş arkadaş", JOB, "muhasebeci")]),
    Case("c1", ["İki Ahmet var. Biri komşum, İzmir'de yaşıyor. Diğeri iş arkadaşım, Ankara'da yaşıyor."],
         "Ahmet", 2, [("komşu", CITY, "İzmir"), ("iş arkadaş", CITY, "Ankara")]),
    Case("t1", ["Üç Ayşe var. Biri kuzenim, doktor. Biri komşum, öğretmen. Diğeri iş arkadaşım, avukat."],
         "Ayşe", 3, [("kuzen", JOB, "doktor"), ("komşu", JOB, "öğretmen"), ("iş arkadaş", JOB, "avukat")]),
    Case("t2", ["Üç Ali var: ilki kuzenim, doktor; ikincisi komşum, avukat; üçüncüsü iş arkadaşım, mimar."],
         "Ali", 3, [("kuzen", JOB, "doktor"), ("komşu", JOB, "avukat"), ("iş arkadaş", JOB, "mimar")]),
    Case("z1", ["İki Zeynep var hayatımda: biri kuzenim, avukat; diğeri eski iş arkadaşım, doktor."], "Zeynep", 2,
         [("kuzen", JOB, "avukat"), ("iş arkadaş", JOB, "doktor")]),
    Case("m1", ["İki Can var. Biri kuzenim, pilot, İstanbul'da yaşıyor. Diğeri komşum, aşçı."], "Can", 2,
         [("kuzen", JOB, "pilot"), ("kuzen", CITY, "İstanbul"), ("komşu", JOB, "aşçı")]),
    Case("r1", ["İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım.",
                "Komşum Ahmet mimar. İş arkadaşım Ahmet muhasebeci."], "Ahmet", 2,
         [("komşu", JOB, "mimar"), ("iş arkadaş", JOB, "muhasebeci")]),
    Case("a1", ["İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım.", "Ahmet'in doğum günü 5 Mayıs."],
         "Ahmet", 2, [], forbid=["Mayıs"]),
    Case("a2", ["İki Ahmet tanıyorum. Biri komşum, diğeri iş arkadaşım. Ahmet emekli oldu."], "Ahmet", 2,
         [], forbid=["emekli"]),
]  # fmt: skip


# ----- the database ---------------------------------------------------------------------------
def people_state(p: Profile, name: str) -> dict[str, Any]:
    key = text.name_key(name)

    def read(c: Any) -> dict[str, Any]:
        ents = [e for e in memory_repo.find_entities(c, key) if e.status == "active"]
        out = []
        for e in ents:
            facts = [{"predicate": m.predicate, "value": m.value, "status": m.status}
                     for m in memory_repo.memories_for_subject(c, e.id)]  # fmt: skip
            out.append({"id": e.id, "relation": e.relation or "", "description": e.description or "",
                        "facts": facts})  # fmt: skip
        inbox = [{"type": i.type, "summary": i.summary}
                 for i in memory_repo.list_inbox(c, status="open", types=("ambiguous_entity",))]  # fmt: skip
        return {"people": out, "inbox": inbox}

    return p.q(read)


def judge(case: Case, people: list[dict[str, Any]]) -> tuple[dict[str, bool], dict[str, Any]]:
    """people: [{"relation", "description", "facts": [{"predicate", "value", "status"}]}]."""
    fold = text.fold
    wrong: list[tuple[str, str]] = []
    found = 0
    for rel_word, preds, part in case.expect:
        on = [(p, m) for p in people for m in p["facts"]
              if m["predicate"] in preds.split("|") and fold(part) in fold(m["value"])]  # fmt: skip
        right = [x for x in on if fold(rel_word) in fold(x[0]["relation"] + " " + x[0]["description"])]
        wrong += [(x[0]["relation"] or x[0]["description"] or "-", x[1]["value"]) for x in on if x not in right]
        found += bool(right)
    forbidden = [(p["relation"] or "-", m["value"]) for p in people for m in p["facts"]
                 for part in case.forbid if fold(part) in fold(m["value"])]  # fmt: skip
    safety = {
        "no_wrong_person": not wrong,
        "no_more_people_than_said": len(people) <= case.count,
        "nothing_said_of_the_bare_name": not forbidden,
    }
    return safety, {"expected": len(case.expect), "found": found, "wrong": wrong, "forbidden": forbidden,
                    "people": len(people)}  # fmt: skip


# ----- chat -------------------------------------------------------------------------------------
async def chat_case(case: Case, rep: int, llm: GuardRecorder, model: str) -> dict[str, Any]:
    p = Profile(model, llm)
    await p.start()
    await p.clean_session()
    turns: list[dict[str, Any]] = []
    try:
        for m in case.messages:
            r = await say(p, llm, T(m))
            r["reply"] = r["done"] if r["done"] is not None else r["shown"]
            turns.append({k: r.get(k) for k in ("user", "reply", "shown", "stored", "same_text", "outcome",
                                                 "claim_state", "shown_claims", "shown_internal")})  # fmt: skip
        st = people_state(p, case.name)
    finally:
        await p.stop()
        p.remove()
    safety, detail = judge(case, st["people"])
    safety["no_shown_claim"] = not any(t["shown_claims"] for t in turns)
    safety["no_internal"] = not any(t["shown_internal"] for t in turns)
    safety["shown_equals_stored"] = all(t["same_text"] for t in turns)
    if case.forbid:  # said of the bare name: asked, or not written at all
        detail["asked"] = bool(st["inbox"]) or bool(re.search(r"\bhangi\b", claims.fold(turns[-1]["reply"] or "")))
    return {"id": f"{case.id}r{rep}", "path": "chat", "passed": all(safety.values()), "safety": safety,
            "detail": detail, "state": st, "turns": turns}  # fmt: skip


async def run_chat(model: str) -> list[dict[str, Any]]:
    llm = GuardRecorder(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200))
    out = []
    try:
        for rep in range(1, REPEATS + 1):
            for case in CASES:
                r = await chat_case(case, rep, llm, model)
                out.append(r)
                print(f"[{'ok  ' if r['passed'] else 'FAIL'}] chat {r['id']} {r['safety']} {r['detail']}", flush=True)
                for t in r["turns"]:
                    print(f"      U: {t['user']}\n      L: {(t['reply'] or '')[:240]!r} [{t['claim_state']}]", flush=True)
                for person in r["state"]["people"]:
                    print(f"      P {case.name} ({person['relation'] or person['description']}): "
                          f"{[(m['predicate'], m['value'], m['status']) for m in person['facts']]}", flush=True)  # fmt: skip
                if r["state"]["inbox"]:
                    print(f"      inbox: {r['state']['inbox']}", flush=True)
    finally:
        await llm.inner.aclose()
    return out


# ----- profile file -----------------------------------------------------------------------------
def file_scenarios() -> list[boot.Scenario]:
    out = []
    for rep in range(1, REPEATS + 1):
        for case in CASES:
            if not case.file:
                continue
            out.append(boot.Scenario(
                f"{case.id}r{rep}", "namesake", "\n\n".join(case.messages), name="profil.txt",
                expect=[((case.name, w), preds, part) for w, preds, part in case.expect],
                forbid=[(case.name, part) for part in case.forbid],
            ))  # fmt: skip
    return out


def file_result(case: Case, r: dict[str, Any]) -> dict[str, Any]:
    by_rel: dict[str, dict[str, Any]] = {}
    for w in r.get("written", []):
        if w["name"] != case.name:
            continue
        p = by_rel.setdefault(w["relation"], {"relation": w["relation"], "description": "", "facts": []})
        p["facts"].append({"predicate": w["predicate"], "value": w["value"], "status": w["status"]})
    safety, detail = judge(case, list(by_rel.values()))
    people = [x for x in r.get("people", []) if x["label"].split(" (")[0] == case.name]
    safety["no_more_people_than_said"] = len(people) <= case.count
    safety.update({f"boot_{k}": v for k, v in r["safety"].items()})
    detail["people"] = len(people)
    return {"id": r["id"], "path": "file", "passed": all(safety.values()), "safety": safety, "detail": detail,
            "warnings": r.get("warnings", []), "proposals": r.get("proposals", []), "written": r.get("written", [])}  # fmt: skip


async def run_file(model: str) -> list[dict[str, Any]]:
    boot.SCENARIOS[:] = file_scenarios()
    report = await boot.run(model, None)
    by_id = {c.id: c for c in CASES}
    out = []
    for r in report["scenarios"]:
        case = by_id[r["id"].rsplit("r", 1)[0]]
        x = file_result(case, r)
        out.append(x)
        print(f"[{'ok  ' if x['passed'] else 'FAIL'}] file {x['id']} {x['safety']} {x['detail']}", flush=True)
    return out


def summary(rs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "runs": len(rs), "safe": sum(r["passed"] for r in rs),
        "wrong_person": sum(len(r["detail"]["wrong"]) for r in rs),
        "bare_name_written": sum(len(r["detail"]["forbidden"]) for r in rs),
        "too_many_people": sum(not r["safety"]["no_more_people_than_said"] for r in rs),
        "facts_expected": sum(r["detail"]["expected"] for r in rs),
        "facts_found": sum(r["detail"]["found"] for r in rs),
        "failed_checks": {k: sum(1 for r in rs if r["safety"].get(k) is False)
                          for k in sorted({k for r in rs for k in r["safety"]})},
    }  # fmt: skip


async def run(model: str, paths: set[str]) -> dict[str, Any]:
    out: dict[str, Any] = {"model": model, "manifest": manifest(model)}
    if "file" in paths:
        out["file"] = await run_file(model)
    if "chat" in paths:
        out["chat"] = await run_chat(model)
    out["summary"] = {k: summary(out[k]) for k in ("file", "chat") if k in out}
    return out


def main() -> None:
    global REPEATS
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:12b-it-qat")
    ap.add_argument("--paths", default="file,chat")
    ap.add_argument("--label", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--repeats", type=int, default=REPEATS)
    args = ap.parse_args()
    REPEATS = args.repeats
    if args.only:
        CASES[:] = [c for c in CASES if c.id in set(args.only.split(","))]
    report = asyncio.run(run(args.model, set(args.paths.split(","))))
    OUT.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[:/]", "_", args.model)
    path = OUT / f"namesakes_{name}{'_' + args.label if args.label else ''}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False), path)


if __name__ == "__main__":
    main()
