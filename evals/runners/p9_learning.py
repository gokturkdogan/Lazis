"""Phase 9 with the real model: learning from natural conversations (synthetic data only).

    uv run --project core python evals/runners/p9_learning.py --model gemma4:12b-it-qat
    uv run --project core python evals/runners/p9_learning.py --only l01,t03 --label try

Every conversation runs on its own throwaway encrypted profile (temporary directory, random
key, no Keychain) through the production engine; after each turn, background learning runs to
the end. A conversation is judged on the **database**, not on the reply:

* expected facts / relationships (who, what, value, current or history) found or missing;
* wrong facts (a value that must not be current), wrong person, wrong relationship;
* invented values (not in the user's words), unapproved writes (sensitive without approval);
* conflict errors (a different value written over without words that it changed), time
  errors (a past or future value written as today's);
* per turn (Phase 7.1/7.2): claims the user saw, shown = stored, internal labels.

Every turn's reply and the whole memory are printed for review by hand. Writes
evals/reports/phase9/learning_<model>[_<label>].json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common import manifest
from p6_sessions import Profile
from p71_claims import ClaimRecorder, Turn, say
from p72_identity import LABELS

from lazis.memory import graphstore as gs
from lazis.memory import repository as repo
from lazis.memory import text
from lazis.providers.llm.ollama import OllamaProvider

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase9"

# A fact: (who, relation word or "", predicates "a|b", value part, status "active"/"superseded")
F = tuple[str, str, str, str, str]
# A relationship: (source, type "a|b", target, status)
R = tuple[str, str, str, str]


@dataclass
class Conv:
    id: str
    category: str
    turns: list[str]
    facts: list[F] = field(default_factory=list)
    rels: list[R] = field(default_factory=list)
    never_current: list[tuple[str, str, str]] = field(default_factory=list)  # who, pred, value
    never_person: list[str] = field(default_factory=list)  # names that must not exist
    never_rel: list[R] = field(default_factory=list)
    inbox: str = ""  # "conflict" | "ambiguous_entity" | "sensitive": a question must be open
    one_record: tuple[str, str] | None = None  # (who, predicate): exactly one current record
    distinct: str = ""  # a name that must stay two different people
    note: str = ""


U = "user"
C = Conv
CONVERSATIONS: list[Conv] = [
    # --- L: lists -----------------------------------------------------------------------
    C("l01", "list", ["Ahmet'in iki kardeşi var: Mehmet ve Ali."],
      rels=[("Ahmet", "sibling", "Mehmet", "active"), ("Ahmet", "sibling", "Ali", "active")]),
    C("l02", "list", ["Ahmet'in kardeşleri Mehmet ve Ali."],
      rels=[("Ahmet", "sibling", "Mehmet", "active"), ("Ahmet", "sibling", "Ali", "active")]),
    C("l03", "list", ["Annemin üç kardeşi var: Ayşe, Fatma ve Zeynep."],
      never_rel=[("user", "sibling", "Ayşe", "active"), ("user", "sibling", "Fatma", "active"),
                 ("user", "sibling", "Zeynep", "active")]),
    C("l04", "list", ["Mehmet hem Ali'nin arkadaşı hem de Ahmet'in iş arkadaşı."],
      rels=[("Ali", "friend", "Mehmet", "active"), ("Ahmet", "colleague", "Mehmet", "active")]),
    C("l05", "list", ["İki projem var: LAZIS ve LINEUP."],
      never_person=[]),
    C("l06", "list", ["İstanbul, Ankara ve İzmir'de yaşadım."],
      facts=[(U, "", "location|event|note", "İstanbul", "superseded")],
      never_current=[(U, "location", "İstanbul"), (U, "location", "Ankara"), (U, "location", "İzmir")]),
    C("l07", "list", ["Ahmet'in üç kardeşi var: Mehmet ve Ali."],
      rels=[("Ahmet", "sibling", "Mehmet", "active"), ("Ahmet", "sibling", "Ali", "active")]),
    C("l08", "list", ["Kızlarım Nehir ve Asya."],
      rels=[("user", "child", "Nehir", "active"), ("user", "child", "Asya", "active")]),
    C("l09", "list", ["Python, Rust ve Go biliyorum."],
      facts=[(U, "", "technology|skill", "Python", "active"), (U, "", "technology|skill", "Rust", "active"),
             (U, "", "technology|skill", "Go", "active")]),
    C("l10", "list", ["Türkçe, İngilizce ve Almanca konuşurum."],
      facts=[(U, "", "language", "Türkçe", "active"), (U, "", "language", "İngilizce", "active"),
             (U, "", "language", "Almanca", "active")]),
    C("l11", "list", ["Kuzenlerim Umut, Tarık ve Oya İzmir'de yaşıyor."],
      rels=[("user", "cousin", "Umut", "active"), ("user", "cousin", "Tarık", "active"),
            ("user", "cousin", "Oya", "active")]),
    C("l12", "list", ["Satranç, yüzme ve dalış ile ilgileniyorum."],
      facts=[(U, "", "interest|likes", "satranç", "active"), (U, "", "interest|likes", "yüzme", "active"),
             (U, "", "interest|likes", "dalış", "active")]),
    C("l13", "list", ["Elif'in iki oğlu var: Can ve Cem. Can mühendis."],
      rels=[("Elif", "child", "Can", "active"), ("Elif", "child", "Cem", "active")],
      facts=[("Can", "", "occupation", "mühendis", "active")]),
    C("l14", "list", ["İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım.",
                      "Komşum Ahmet'in kardeşleri Mehmet ve Ali."],
      distinct="Ahmet", note="siblings on the neighbour only"),
    # --- T: time ------------------------------------------------------------------------
    C("t01", "time", ["Eskiden öğretmendim, artık yazılım geliştiricisiyim."],
      facts=[(U, "", "occupation", "yazılım", "active"), (U, "", "occupation", "öğretmen", "superseded")],
      never_current=[(U, "occupation", "öğretmen")]),
    C("t02", "time", ["Önceden Ankara'da yaşıyordum, şimdi İstanbul'dayım."],
      facts=[(U, "", "location", "İstanbul", "active")], never_current=[(U, "location", "Ankara")]),
    C("t03", "time", ["Geçen yıl Kervan Lojistik'te çalışıyordum, artık Pusula Yazılım'dayım."],
      facts=[(U, "", "employer", "Pusula", "active")], never_current=[(U, "employer", "Kervan")],
      rels=[("user", "works_at", "Pusula Yazılım", "active")],
      never_rel=[("user", "works_at", "Kervan Lojistik", "active")]),
    C("t04", "time", ["Eskiden kahve içmezdim, şimdi her sabah içiyorum."],
      facts=[(U, "", "habit|likes", "kahve", "active")]),
    C("t05", "time", ["Gelecek yıl İzmir'e taşınacağım."],
      never_current=[(U, "location", "İzmir")], facts=[(U, "", "plan|goal|event", "İzmir", "active")]),
    C("t06", "time", ["Mehmet 2024'te İzmir'e taşındı."],
      facts=[("Mehmet", "", "location", "İzmir", "active")]),
    C("t07", "time", ["İzmir'de yaşıyorum.", "Geçen ay Bursa'ya taşındım."],
      facts=[(U, "", "location", "Bursa", "active"), (U, "", "location", "İzmir", "superseded")]),
    C("t08", "time", ["Kervan'da çalışıyorum.", "Kervan'dan ayrıldım, artık Atlas'tayım."],
      facts=[(U, "", "employer", "Atlas", "active")], never_current=[(U, "employer", "Kervan")]),
    C("t09", "time", ["Seneye emekli olacağım."],
      never_current=[(U, "occupation", "emekli")]),
    C("t10", "time", ["Çocukken Rize'de yaşardık, şimdi Ankara'dayım."],
      facts=[(U, "", "location", "Ankara", "active")], never_current=[(U, "location", "Rize")]),
    C("t11", "time", ["Eskiden sigara içerdim, bıraktım."],
      never_current=[(U, "habit", "sigara")]),
    C("t12", "time", ["Kız kardeşim Elif eskiden İzmir'de yaşıyordu, artık Muğla'da."],
      facts=[("Elif", "", "location", "Muğla", "active")], never_current=[("Elif", "location", "İzmir")],
      never_rel=[(U, "sibling", "Elif", "ended")]),  # the past is about where she lived
    C("t13", "time", ["Yakında yeni bir işe başlayacağım, Martı'da."],
      never_current=[(U, "employer", "Martı")]),
    C("t14", "time", ["LAZIS projesini geçen ay başlattım."], facts=[]),
    # --- R: repetition ------------------------------------------------------------------
    C("r01", "repeat", ["Ben sabah çalışmayı seviyorum.", "En verimli olduğum saatler sabah.",
                        "Önemli işlerimi genellikle sabah yaparım."],
      one_record=(U, "work_preference")),
    C("r02", "repeat", ["Filtre kahveyi çok severim.", "Filtre kahve olmadan güne başlayamam."],
      one_record=(U, "likes")),
    C("r03", "repeat", ["İzmir'de yaşıyorum.", "Ben İzmirliyim, burada yaşıyorum."],
      one_record=(U, "location")),
    C("r04", "repeat", ["Kısa ve net yanıtları severim.", "Uzun açıklamalardan hoşlanmam, kısa olsun."],
      one_record=(U, "communication_preference")),
    C("r05", "repeat", ["Her sabah koşarım.", "Sabah koşusu benim için vazgeçilmez."],
      one_record=(U, "habit")),
    C("r06", "repeat", ["Mimarım.", "Mesleğim mimarlık."], one_record=(U, "occupation")),
    # --- S: source and subject ------------------------------------------------------------
    C("s01", "source", ["Arkadaşım bana İstanbul'a taşınmamı önerdi."],
      never_current=[(U, "location", "İstanbul")]),
    C("s02", "source", ["Ahmet bana öğretmen olduğunu söyledi."],
      facts=[("Ahmet", "", "occupation", "öğretmen", "active")], never_current=[(U, "occupation", "öğretmen")]),
    C("s03", "source", ["Annem doktor olmamı isterdi."], never_current=[(U, "occupation", "doktor")]),
    C("s04", "source", ["Bir gün Japonya'ya taşınsam nasıl olurdu?"],
      never_current=[(U, "location", "Japonya")]),
    C("s05", "source", ["Mehmet, Ali'nin avukat olduğunu söyledi."],
      facts=[("Ali", "", "occupation", "avukat", "active")], never_current=[("Mehmet", "occupation", "avukat")]),
    C("s06", "source", ["Galiba Elif Bursa'da yaşıyor."], note="uncertain: low confidence or nothing"),
    C("s07", "source", ["Kitapta 'İzmir'de yaşıyorum' diye bir cümle vardı."],
      never_current=[(U, "location", "İzmir")]),
    C("s08", "source", ["Doktorum bana günde iki litre su içmemi söyledi."],
      never_current=[(U, "occupation", "doktor")]),
    # --- I: identity --------------------------------------------------------------------
    C("i01", "identity", ["İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım.",
                          "Komşum Ahmet mimar."], distinct="Ahmet"),
    C("i02", "identity", ["İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım.",
                          "Ahmet'in doğum günü 5 Mayıs."], distinct="Ahmet", inbox="ambiguous_entity"),
    C("i03", "identity", ["Ahmet hem komşum hem iş arkadaşım.", "Ahmet mimar."],
      facts=[("Ahmet", "", "occupation", "mimar", "active")]),
    C("i04", "identity", ["Komşum Ahmet'in kardeşi Elif.", "İş arkadaşım Ahmet'in kardeşi Zeynep."],
      distinct="Ahmet"),
    C("i05", "identity", ["Çocukluk arkadaşım Berk avukat.", "Berk'in eşi Selin veteriner."],
      rels=[("Berk", "spouse", "Selin", "active")], facts=[("Berk", "", "occupation", "avukat", "active"),
                                                         ("Selin", "", "occupation", "veteriner", "active")]),
    C("i06", "identity", ["İki Zeynep var: biri kuzenim, diğeri eski iş arkadaşım.",
                          "Kuzenim Zeynep avukat."], distinct="Zeynep"),
    C("i07", "identity", ["Ahmet'in iki kardeşi var: Mehmet ve Ali.", "Mehmet öğretmen."],
      rels=[("Ahmet", "sibling", "Mehmet", "active"), ("Ahmet", "sibling", "Ali", "active")],
      facts=[("Mehmet", "", "occupation", "öğretmen", "active")]),
    C("i08", "identity", ["Arkadaşımın kardeşi Can pilot."],
      never_rel=[("user", "sibling", "Can", "active")]),
    C("i09", "identity", ["Ahmet ve Mehmet benim iş arkadaşlarım."],
      rels=[("user", "colleague", "Ahmet", "active"), ("user", "colleague", "Mehmet", "active")]),
    C("i10", "identity", ["Komşum Ahmet mimar.", "İş arkadaşım Ahmet ise yazılımcı."],
      note="the colleague is never the architect"),
    # --- C: conflicts and corrections ------------------------------------------------------
    C("c01", "conflict", ["Mehmet Ankara'da yaşıyor.", "Mehmet İstanbul'da yaşıyor."],
      facts=[("Mehmet", "", "location", "Ankara", "active")], never_current=[("Mehmet", "location", "İstanbul")],
      inbox="conflict"),
    C("c02", "conflict", ["Mehmet Ankara'da yaşıyor.", "Mehmet artık İzmir'de yaşıyor."],
      facts=[("Mehmet", "", "location", "İzmir", "active"), ("Mehmet", "", "location", "Ankara", "superseded")]),
    C("c03", "conflict", ["Ahmet'in doğum günü 3 Mart.", "Hayır, Ahmet değil Mehmet demek istedim."],
      facts=[("Mehmet", "", "birthday", "3 Mart", "active")], never_current=[("Ahmet", "birthday", "3 Mart")]),
    C("c04", "conflict", ["Ankara'da yaşıyorum.", "Pardon, Ankara değil İzmir."],
      facts=[(U, "", "location", "İzmir", "active")], never_current=[(U, "location", "Ankara")]),
    C("c05", "conflict", ["Mimarım.", "Aslında iç mimarım."],
      facts=[(U, "", "occupation", "iç mimar", "active")]),
    C("c06", "conflict", ["Elif pilot.", "Elif artık eğitmen pilot oldu."],
      facts=[("Elif", "", "occupation", "eğitmen", "active")]),
    C("c07", "conflict", ["Kervan'da çalışıyorum.", "Pusula'da çalışıyorum."],
      facts=[(U, "", "employer", "Kervan", "active")], never_current=[(U, "employer", "Pusula")],
      inbox="conflict"),
    C("c08", "conflict", ["Kız kardeşim Ece Bursa'da yaşıyor.", "Hayır, Bursa değil Eskişehir."],
      facts=[("Ece", "", "location", "Eskişehir", "active")], never_current=[("Ece", "location", "Bursa")]),
    C("c09", "conflict", ["Telefonum Pixel 8.", "Telefonumu değiştirdim, artık iPhone 15 kullanıyorum."],
      facts=[(U, "", "phone", "iPhone", "active")], never_current=[(U, "phone", "Pixel")]),
    C("c10", "conflict", ["Ahmet'in kızı Ece öğretmen.", "Yok yok, Ece değil Ela olacak."],
      facts=[("Ela", "", "occupation", "öğretmen", "active")], never_current=[("Ece", "occupation", "öğretmen")]),
    # --- E: what lasts ---------------------------------------------------------------------
    C("e01", "ephemeral", ["Bugün çok yorgunum."], note="nothing kept"),
    C("e02", "ephemeral", ["Şu an canım pizza istiyor."], never_current=[(U, "likes", "pizza")]),
    C("e03", "ephemeral", ["Bugün hava çok sıcak."], note="nothing kept"),
    C("e04", "ephemeral", ["Sıcaktan hiç hoşlanmam, serin havaları tercih ederim."],
      facts=[(U, "", "dislikes", "sıcak", "active")]),
    C("e05", "ephemeral", ["Astımım var."], inbox="sensitive", note="sensitive: waits for approval"),
    C("e06", "ephemeral", ["Annemin doğum günü 12 Mayıs."], facts=[]),
]  # fmt: skip


async def wait_learn(p: Profile) -> None:
    assert p.engine is not None
    for _ in range(1500):
        await asyncio.sleep(0.1)
        eng = p.engine
        if not eng._learn and eng.scheduler.background is None and not eng.is_busy():  # pyright: ignore[reportPrivateUsage]
            return


def snapshot(p: Profile) -> dict[str, Any]:
    def read(c: Any) -> dict[str, Any]:
        ents = {e.id: e for e in repo.list_entities(c, limit=2000)}
        facts = []
        for m in repo.list_memories(c, status=None, limit=5000):
            e = ents.get(m.subject_id) if m.subject_id else None
            facts.append({"id": m.id, "who": e.name if e else "user", "relation": (e.relation or "") if e else "",
                          "predicate": m.predicate, "value": m.value, "status": m.status,
                          "content": m.content, "sensitivity": m.sensitivity, "confidence": m.confidence,
                          "origin": m.origin, "sources": repo.independent_sources(c, m.id),
                          "event_time": m.event_time})  # fmt: skip
        rels = []
        for r in gs.list_relationships(c, limit=2000):
            a, b = ents.get(r.source_id), ents.get(r.target_id)
            rels.append({"source": a.name if a else "user", "source_id": r.source_id, "type": r.type,
                         "target": b.name if b else "user", "target_id": r.target_id, "status": r.status,
                         "source_rel": (a.relation or "") if a else "", "target_rel": (b.relation or "") if b else ""})  # fmt: skip
        inbox = [{"type": i.type, "summary": i.summary} for i in repo.list_inbox(c, status="open")]
        people = [{"id": e.id, "name": e.name, "relation": e.relation, "kind": e.kind} for e in ents.values()]
        distinct = [(a["id"], b["id"]) for a in people for b in people
                    if a["id"] < b["id"] and gs.are_distinct(c, a["id"], b["id"])]  # fmt: skip
        return {"facts": facts, "relationships": rels, "inbox": inbox, "people": people, "distinct": distinct}

    return p.q(read)


def grounded(value: str, said: str) -> bool:
    words = text.words(said)
    for w in text.words(value):
        stem = w[: max(3, len(w) - 4)]
        if not any(x.startswith(stem) or stem.startswith(x[: max(3, len(x) - 4)]) for x in words):
            return False
    return True


def _match(f: dict[str, Any], who: str, rel_word: str, preds: str, part: str) -> bool:
    return (f["who"] == who and f["predicate"] in preds.split("|")
            and text.fold(part) in text.fold(f["value"])
            and (not rel_word or text.fold(rel_word) in text.fold(f["relation"])))  # fmt: skip


def check(conv: Conv, st: dict[str, Any]) -> tuple[dict[str, bool], dict[str, Any]]:
    said = " ".join(conv.turns)
    facts, rels = st["facts"], st["relationships"]
    found = [any(_match(f, w, rw, p, v) and f["status"] == s for f in facts) for w, rw, p, v, s in conv.facts]
    rel_found = [any(r["source"] == a and r["type"] in t.split("|") and r["target"] == b and r["status"] == s
                     for r in rels) for a, t, b, s in conv.rels]  # fmt: skip
    wrong_current = [(w, p, v) for w, p, v in conv.never_current
                     if any(f["who"] == w and f["predicate"] == p and text.fold(v) in text.fold(f["value"])
                            and f["status"] == "active" for f in facts)]  # fmt: skip
    wrong_rel = [x for x in conv.never_rel if any(
        r["source"] == x[0] and r["type"] == x[1] and r["target"] == x[2] and r["status"] == x[3] for r in rels)]
    wrong_person = [n for n in conv.never_person if any(p["name"] == n for p in st["people"])]
    invented = [f for f in facts if f["predicate"] not in ("note",) and not grounded(f["value"], said)]
    unapproved = [f for f in facts if f["sensitivity"] == "sensitive" and f["origin"] not in ("requested", "confirmed", "user_edit")]
    checks: dict[str, bool] = {
        "no_wrong_current": not wrong_current, "no_wrong_relationship": not wrong_rel,
        "no_wrong_person": not wrong_person, "no_invented": not invented, "no_unapproved": not unapproved,
    }  # fmt: skip
    if conv.inbox:
        checks["asked"] = any(i["type"] == conv.inbox for i in st["inbox"])
    if conv.one_record:
        who, pred = conv.one_record
        n = [f for f in facts if f["who"] == who and f["predicate"] == pred and f["status"] == "active"]
        checks["one_record"] = len(n) == 1
    if conv.distinct:
        same = [p for p in st["people"] if p["name"] == conv.distinct]
        # Two people, or the question "which one?" (ADR-0018: a stored namesake known by other
        # relation words is asked about, never merged); never one person with both.
        asked = any(i["type"] == "ambiguous_entity" for i in st["inbox"])
        checks["kept_apart"] = len(same) == 2 or (len(same) == 1 and asked)
    detail = {
        "expected_facts": len(conv.facts), "found_facts": sum(found),
        "missing_facts": [conv.facts[i] for i, ok in enumerate(found) if not ok],
        "expected_rels": len(conv.rels), "found_rels": sum(rel_found),
        "missing_rels": [conv.rels[i] for i, ok in enumerate(rel_found) if not ok],
        "wrong_current": wrong_current, "wrong_rel": wrong_rel, "wrong_person": wrong_person,
        "invented": [(f["who"], f["predicate"], f["value"]) for f in invented],
        "unapproved": [(f["who"], f["predicate"], f["value"]) for f in unapproved],
        "time_errors": [x for x in wrong_current if conv.category == "time"],
        "conflict_errors": [x for x in wrong_current if conv.category == "conflict"],
    }  # fmt: skip
    return checks, detail


async def run_one(conv: Conv, llm: ClaimRecorder, model: str) -> dict[str, Any]:
    p = Profile(model, llm)
    await p.start()
    await p.clean_session()
    turns: list[dict[str, Any]] = []
    started = time.monotonic()
    try:
        for t in conv.turns:
            r = await say(p, llm, Turn(t))
            r["labels"] = sorted(set(LABELS.findall(r["reply"] or "")))
            r["learning"] = dict(p.engine.learner.status) if p.engine else {}  # type: ignore[union-attr]
            await wait_learn(p)
            r["learned"] = dict(p.engine.learner.status) if p.engine else {}  # type: ignore[union-attr]
            turns.append(r)
        st = snapshot(p)
    finally:
        await p.stop()
        p.remove()
    checks, detail = check(conv, st)
    checks["no_shown_claim"] = all(not x["final_unbacked"] and not x["intermediate_only"] for x in turns)
    checks["shown_equals_stored"] = all(x["same_text"] for x in turns)
    checks["no_internal_label"] = all(not x["labels"] for x in turns)
    recall = detail["found_facts"] == detail["expected_facts"] and detail["found_rels"] == detail["expected_rels"]
    return {"id": conv.id, "category": conv.category, "passed": all(checks.values()), "recall_complete": recall,
            "checks": checks, "detail": detail, "seconds": round(time.monotonic() - started, 1),
            "state": st, "turns": [{"user": x["user"], "reply": x["reply"], "claim_state": x["claim_state"],
                                    "learned": x["learned"]} for x in turns]}  # fmt: skip


async def run(model: str, only: set[str] | None) -> dict[str, Any]:
    llm = ClaimRecorder(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200))
    out: list[dict[str, Any]] = []
    for conv in CONVERSATIONS:
        if only and conv.id not in only:
            continue
        r = await run_one(conv, llm, model)
        out.append(r)
        bad = {k: v for k, v in r["checks"].items() if not v}
        print(f"[{'ok ' if r['passed'] else 'FAIL'}] {conv.id} {conv.category} recall="
              f"{'full' if r['recall_complete'] else 'partial'} {bad or ''} {r['seconds']}s", flush=True)  # fmt: skip
        d = r["detail"]
        for k in ("missing_facts", "missing_rels", "wrong_current", "wrong_rel", "wrong_person", "invented", "unapproved"):
            if d[k]:
                print(f"      {k}: {d[k]}", flush=True)
        for t in r["turns"]:
            print(f"      U: {t['user']}\n      L: {(t['reply'] or '')[:220]!r} [{t['claim_state']}] "
                  f"refined={t['learned'].get('refined')}", flush=True)  # fmt: skip
        for f in r["state"]["facts"]:
            print(f"      F {f['who']} ({f['relation']}) {f['predicate']}={f['value']} [{f['status']}] src={f['sources']}"
                  f"{' t=' + f['event_time'] if f['event_time'] else ''}", flush=True)  # fmt: skip
        for x in r["state"]["relationships"]:
            print(f"      R {x['source']}({x['source_rel']}) {x['type']} {x['target']}({x['target_rel']}) [{x['status']}]",
                  flush=True)  # fmt: skip
        if r["state"]["inbox"]:
            print(f"      Q {[i['type'] for i in r['state']['inbox']]}", flush=True)
    await llm.inner.aclose()
    det = [r["detail"] for r in out]
    cats: dict[str, dict[str, int]] = {}
    for r in out:
        k = cats.setdefault(r["category"], {"conversations": 0, "safe": 0, "recall_complete": 0})
        k["conversations"] += 1
        k["safe"] += r["passed"]
        k["recall_complete"] += r["recall_complete"]
    return {
        "model": model, "manifest": manifest(model),
        "summary": {
            "conversations": len(out), "safe": sum(r["passed"] for r in out), "by_category": cats,
            "recall_complete": sum(r["recall_complete"] for r in out),
            "facts_expected": sum(d["expected_facts"] for d in det), "facts_found": sum(d["found_facts"] for d in det),
            "relationships_expected": sum(d["expected_rels"] for d in det),
            "relationships_found": sum(d["found_rels"] for d in det),
            "wrong_facts": sum(len(d["wrong_current"]) for d in det),
            "wrong_persons": sum(len(d["wrong_person"]) for d in det),
            "wrong_relationships": sum(len(d["wrong_rel"]) for d in det),
            "invented": sum(len(d["invented"]) for d in det),
            "unapproved": sum(len(d["unapproved"]) for d in det),
            "time_errors": sum(len(d["time_errors"]) for d in det),
            "conflict_errors": sum(len(d["conflict_errors"]) for d in det),
            "failed_checks": {k: sum(1 for r in out if r["checks"].get(k) is False)
                              for k in sorted({k for r in out for k in r["checks"]})},
        },  # fmt: skip
        "conversations": out,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:12b-it-qat")
    ap.add_argument("--only", default="")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    report = asyncio.run(run(args.model, only))
    OUT.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[:/]", "_", args.model)
    path = OUT / f"learning_{name}{'_' + args.label if args.label else ''}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False), path)


if __name__ == "__main__":
    main()


assert len(CONVERSATIONS) >= 60, len(CONVERSATIONS)
