"""Phase 7.2 with the real model: namesakes, explicit requests, internal labels (synthetic data).

    uv run --project core python evals/runners/p72_identity.py --model gemma4:12b-it-qat
    uv run --project core python evals/runners/p72_identity.py --model gemma4:12b-it-qat --only n02,c11

Every conversation runs on its own throwaway encrypted profile through the production engine.
A conversation passes on the **database state**, not on the reply: how many people of a name
exist and with which relationships, which record got the fact (by entity id), that nothing was
written while a name was ambiguous. Per turn, as in Phase 7.1: the shown text, every text seen
while it streamed, the stored text, the claim state, and an independent check for unbacked
memory claims; plus a check for internal labels in the reply. Replies are also reviewed by hand
(the report says which). Writes evals/reports/phase7_2/identity_<model>[_<label>].json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common import manifest
from p6_sessions import Profile
from p71_claims import ClaimRecorder, Turn, say, unbacked

from lazis.memory import graphstore as gs
from lazis.memory import repository as memory_repo
from lazis.providers.llm.ollama import OllamaProvider

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase7_2"
LABELS = re.compile(r"HAFIZA İŞLEMİ|KİŞİSEL HAFIZA|SİSTEM NOTU|===|bildirim(?:i|inde|e)\b|sistem not", re.I)


@dataclass
class State:
    people: list[dict[str, Any]]  # every entity: id, name, relation, description
    facts: list[dict[str, Any]]  # every memory: subject id/name/relation, predicate, value
    open_questions: int
    distinct: set[tuple[str, str]]
    relations: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def named(self, name: str) -> list[dict[str, Any]]:
        return [p for p in self.people if p["name"] == name]

    def facts_of(self, entity_id: str | None) -> list[tuple[str, str]]:
        return [(f["predicate"], f["value"]) for f in self.facts if f["subject_id"] == entity_id]

    def with_relation(self, name: str, word: str) -> list[dict[str, Any]]:
        return [p for p in self.named(name) if word in (p["relation"] or "") + (p["description"] or "")]

    def has_fact(self, predicate: str, value_part: str) -> list[str | None]:
        return [f["subject_id"] for f in self.facts
                if f["predicate"] == predicate and value_part.lower() in f["value"].lower()]  # fmt: skip

    def any_fact(self, value_part: str) -> list[str | None]:
        return [f["subject_id"] for f in self.facts
                if value_part.lower() in (f["value"] + " " + f["content"]).lower()]  # fmt: skip


def snapshot(p: Profile) -> State:
    def read(c: Any) -> State:
        ents = memory_repo.list_entities(c, limit=500)
        people = [{"id": e.id, "name": e.name, "relation": e.relation, "description": e.description}
                  for e in ents]  # fmt: skip
        names = {e.id: e for e in ents}
        facts = []
        for m in memory_repo.list_memories(c, limit=1000):
            e = names.get(m.subject_id) if m.subject_id else None
            facts.append({"subject_id": m.subject_id, "subject": e.name if e else "user",
                          "relation": e.relation if e else None, "predicate": m.predicate,
                          "value": m.value, "content": m.content})  # fmt: skip
        inbox = memory_repo.list_inbox(c, status="open", types=("ambiguous_entity",))
        distinct = {(a["id"], b["id"]) for a in people for b in people
                    if a["id"] < b["id"] and gs.are_distinct(c, a["id"], b["id"])}  # fmt: skip
        rels = []
        for r in gs.list_relationships(c, limit=500):
            a, b = names.get(r.source_id), names.get(r.target_id)
            rels.append({"source": a.name if a else "user", "type": r.type,
                         "target": b.name if b else "user", "status": r.status})  # fmt: skip
        return State(people, facts, len(inbox), distinct, rels)

    return p.q(read)


@dataclass
class Conv:
    id: str
    category: str  # namesake | command | label
    turns: list[Turn | str]  # "RESTART": quit and reopen the app between turns
    check: Callable[[State, list[dict[str, Any]]], dict[str, bool]]
    note: str = ""


def T(m: str, broken: bool = False) -> Turn:  # noqa: N802
    return Turn(m, break_commands=broken)


def only_one(s: State, name: str, predicate: str, value: str, relation_word: str) -> dict[str, bool]:
    """The fact is on exactly the namesake the user meant, and on no other."""
    holders = s.has_fact(predicate, value)
    right = [p["id"] for p in s.with_relation(name, relation_word)]
    return {"on_the_right_one": len(holders) == 1 and holders[0] in right,
            "on_no_other": all(h in right for h in holders)}  # fmt: skip


def nobody(s: State, predicate: str, value: str) -> dict[str, bool]:
    return {"written_to_nobody": s.has_fact(predicate, value) == []}


TWO = "İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım."
TWO_B = "İki Ahmet tanıyorum. Biri komşum, diğeri iş arkadaşım."
BDAY = "Ahmet'in doğum günü 5 Mayıs, bunu unutma."


def two_ahmets(s: State) -> dict[str, bool]:
    a = s.named("Ahmet")
    return {"two_ahmets": len(a) == 2,
            "neighbour_and_colleague": bool(s.with_relation("Ahmet", "komşu")) and bool(s.with_relation("Ahmet", "iş arkadaşı")),
            "marked_different": len(a) == 2 and (min(a[0]["id"], a[1]["id"]), max(a[0]["id"], a[1]["id"])) in s.distinct}  # fmt: skip


def outcome(turns: list[dict[str, Any]], i: int) -> str | None:
    return turns[i]["outcome"]


CONVERSATIONS: list[Conv] = [
    # ----- namesakes -------------------------------------------------------------------------
    Conv("n01", "namesake", [T(TWO)], lambda s, t: two_ahmets(s)),
    Conv("n02", "namesake", [T(TWO_B), T(BDAY), T("Komşum olan.")],
         lambda s, t: {**two_ahmets(s), "asked_first": outcome(t, 1) == "ambiguous",
                       "saved_after_answer": outcome(t, 2) == "saved",
                       **only_one(s, "Ahmet", "birthday", "5 Mayıs", "komşu")}),
    Conv("n03", "namesake", [T("İki Mehmet tanıyorum, biri öğretmen, diğeri mühendis."),
                             T("Bunu unutma: Mehmet'in doğum günü 3 Nisan."), T("Mühendis olan Mehmet.")],
         lambda s, t: {"two_mehmets": len(s.named("Mehmet")) == 2, "asked": outcome(t, 1) == "ambiguous",
                       "on_the_engineer": [h for h in s.has_fact("birthday", "3 Nisan")]
                       == [m["id"] for m in s.named("Mehmet") if ("occupation", "mühendis") in s.facts_of(m["id"])
                           or "mühendis" in (m["description"] or "")][:1]}),
    Conv("n04", "namesake", [T("Üç Ayşe var hayatımda: kuzenim, komşum ve iş arkadaşım."),
                             T("Ayşe'nin doğum günü 1 Ocak, not al."), T("İş arkadaşım olan.")],
         lambda s, t: {"three_ayse": len(s.named("Ayşe")) == 3, "asked": outcome(t, 1) == "ambiguous",
                       **only_one(s, "Ayşe", "birthday", "1 Ocak", "iş arkadaşı")}),
    Conv("n05", "namesake", [T("İki Murat var; biri eski iş arkadaşım, diğeri çocukluk arkadaşım.")],
         lambda s, t: {"two_murats": len(s.named("Murat")) == 2,
                       "childhood_friend": bool(s.with_relation("Murat", "çocukluk"))}),
    Conv("n06", "namesake", [T("Ahmet ve Mehmet benim iş arkadaşlarım.")],
         lambda s, t: {"one_ahmet": len(s.named("Ahmet")) == 1, "one_mehmet": len(s.named("Mehmet")) == 1}),
    Conv("n07", "namesake", [T("Ahmet'in iki kardeşi var: Mehmet ve Ali.")],
         lambda s, t: {"one_each": [len(s.named(n)) for n in ("Ahmet", "Mehmet", "Ali")] == [1, 1, 1]}),
    Conv("n08", "namesake", [T("Ahmet hem komşum hem iş arkadaşım.")],
         lambda s, t: {"one_ahmet": len(s.named("Ahmet")) == 1, "no_question": s.open_questions == 0}),
    Conv("n09", "namesake", [T("Komşum Ahmet mimar."), T("İş arkadaşım Ahmet ise yazılımcı.")],
         lambda s, t: {"neighbour_not_a_developer": all(
             ("occupation", "yazılımcı") not in s.facts_of(p["id"]) for p in s.with_relation("Ahmet", "komşu")),
             "architect_kept": bool(s.has_fact("occupation", "mimar"))}),
    Conv("n10", "namesake", [T(TWO), T(BDAY), T("Vazgeç.")],
         lambda s, t: {**nobody(s, "birthday", "5 Mayıs"), "cancelled": outcome(t, 2) == "cancelled"}),
    Conv("n11", "namesake", [T(TWO), T(BDAY), T("Komşum olan."), T("Hayır, iş arkadaşım olan.")],
         lambda s, t: {"moved": outcome(t, 3) == "corrected", **only_one(s, "Ahmet", "birthday", "5 Mayıs", "iş arkadaşı")}),
    Conv("n12", "namesake", [T("İki Zeynep var, biri kuzenim, diğeri komşum."), T("Zeynep'in kızı geçen hafta doğdu.")],
         lambda s, t: {"two_zeynep": len(s.named("Zeynep")) == 2,
                       "held_not_guessed": all(s.facts_of(z["id"]) == [] for z in s.named("Zeynep"))}),
    Conv("n13", "namesake", [T("İki Ahmet Yılmaz tanıyorum: biri komşum, diğeri eski patronum."),
                             T("Ahmet Yılmaz'ın doğum günü 5 Mayıs, bunu unutma.")],
         lambda s, t: {"two": len(s.named("Ahmet Yılmaz")) == 2, "asked": outcome(t, 1) == "ambiguous",
                       **nobody(s, "birthday", "5 Mayıs")}),
    Conv("n14", "namesake", [T("İki Çağla var: biri kuzenim, diğeri komşum."), T("Çağla'nın doğum günü 9 Eylül, not al."),
                             T("Kuzenim olan.")],
         lambda s, t: {"two": len(s.named("Çağla")) == 2, **only_one(s, "Çağla", "birthday", "9 Eylül", "kuzen")}),
    Conv("n15", "namesake", [T("Ahmet adında iki arkadaşım var: biri üniversiteden arkadaşım, diğeri eski patronum.")],
         lambda s, t: {"two": len(s.named("Ahmet")) == 2}),
    Conv("n16", "namesake", [T(TWO), T(BDAY), T("Komşum Ahmet yarın akşam bize yemeğe gelecek.")],
         lambda s, t: {**nobody(s, "birthday", "5 Mayıs"), "question_still_open": s.open_questions >= 1}),
    Conv("n17", "namesake", [T(TWO), T(BDAY), "RESTART", T("Komşum olan.")],
         lambda s, t: only_one(s, "Ahmet", "birthday", "5 Mayıs", "komşu")),
    Conv("n18", "namesake", [T("İki Mehmet tanıyorum: biri iş arkadaşım, diğeri de iş arkadaşım."),
                             T("Mehmet'in doğum günü 2 Şubat, bunu unutma.")],
         lambda s, t: {"two": len(s.named("Mehmet")) == 2, **nobody(s, "birthday", "2 Şubat")}),
    # ----- explicit requests -----------------------------------------------------------------
    Conv("c01", "command", [T("Lütfen şunu not al: Murat'ın doğum günü 12 Haziran.")],
         lambda s, t: {"saved": outcome(t, 0) == "saved", "on_murat": s.has_fact("birthday", "12 Haziran")
                       == [m["id"] for m in s.named("Murat")]}),
    Conv("c02", "command", [T("Bunu unutma: Burak'ın düğünü haziranda.")],
         lambda s, t: {"saved": outcome(t, 0) == "saved", "on_burak": bool(s.named("Burak")) and
                       any(s.facts_of(b["id"]) for b in s.named("Burak"))}),
    Conv("c03", "command", [T("Şunu hafızana kaydet: Elif vejetaryen.")],
         lambda s, t: {"saved": outcome(t, 0) == "saved", "written": bool(s.any_fact("vejetaryen"))}),
    Conv("c04", "command", [T("Bunu not et: arabanın sigortası mart ayında bitiyor.")],
         lambda s, t: {"saved": outcome(t, 0) == "saved", "not_the_users_birthday": s.has_fact("birthday", "mart") == []}),
    Conv("c05", "command", [T("Not al: kira her ayın beşinde ödeniyor.")],
         lambda s, t: {"saved": outcome(t, 0) == "saved", "not_technology": s.has_fact("technology", "beşinde") == []}),
    Conv("c06", "command", [T("Aklında tut: kızımın okul servisi 7.40'ta geliyor.")],
         lambda s, t: {"saved": outcome(t, 0) == "saved", "written": bool(s.any_fact("7.40"))}),
    Conv("c07", "command", [T("Bu bilgiyi unutmanı istemiyorum: Can laktoz yemiyor.")],
         lambda s, t: {"saved": outcome(t, 0) == "saved", "written": bool(s.any_fact("laktoz"))}),
    Conv("c08", "command", [T("Bunu ileride hatırlamanı istiyorum: annemin doğum günü 3 Mart.")],
         lambda s, t: {"saved": outcome(t, 0) == "saved", "written": bool(s.any_fact("3 Mart"))}),
    Conv("c09", "command", [T("Not düş: su faturası her ayın 20'sinde geliyor.")],
         lambda s, t: {"saved": outcome(t, 0) == "saved", "written": bool(s.any_fact("20"))}),
    Conv("c10", "command", [T("Şunu bilmeni istiyorum, unutma: Selin'in kedisinin adı Duman.")],
         lambda s, t: {"saved": outcome(t, 0) == "saved", "written": bool(s.any_fact("Duman")) or any(
             "Duman" in (r["source"], r["target"]) for r in s.relations)}),
    Conv("c11", "command", [T("Elif'in doğum günü 12 Mart."), T("Bunu unutma.")],
         lambda s, t: {"saved": outcome(t, 1) == "saved",
                       "on_elif": s.has_fact("birthday", "12 Mart") == [e["id"] for e in s.named("Elif")]}),
    Conv("c12", "command", [T("Mehmet benim eski iş arkadaşım, bunu unutma.")],
         lambda s, t: {"saved": outcome(t, 0) in ("saved", "corrected"), "mehmet": len(s.named("Mehmet")) == 1}),
    Conv("c13", "command", [T("Bana kısa bir toplantı notu hazırla.")],
         lambda s, t: {"no_request": t[0]["request"] is None, "nothing_written": s.facts == []}),
    Conv("c14", "command", [T("Not almak için hangi uygulamayı önerirsin?")],
         lambda s, t: {"no_request": t[0]["request"] is None, "nothing_written": s.facts == []}),
    Conv("c15", "command", [T("“Bunu not al” ifadesini İngilizceye çevir.")],
         lambda s, t: {"no_request": t[0]["request"] is None, "nothing_written": s.facts == []}),
    Conv("c16", "command", [T("Not al: banka kartımın şifresi 4471.")],
         lambda s, t: {"secret_refused": outcome(t, 0) == "secret_not_stored", "nothing_written": s.facts == []}),
    # The request fails (the command model's answer is corrupted on purpose): the reply must say
    # so. Background learning may still learn the statement afterwards (by design, ADR-0015).
    Conv("c17", "command", [T("Lütfen şunu not al: Ece'nin doğum günü 1 Ekim.", broken=True)],
         lambda s, t: {"failed": outcome(t, 0) == "failed", "reply_says_not_saved": "kaydedeme" in
                       (t[0]["reply"] or "").lower() or "kaydedileme" in (t[0]["reply"] or "").lower()}),
    Conv("c18", "command", [T("Lütfen şunu not al.")],
         lambda s, t: {"nothing_to_save": outcome(t, 0) == "nothing", "nothing_written": s.facts == []}),
    # ----- internal labels and natural replies -----------------------------------------------
    Conv("l01", "label", [T("Tariflerimi hatırlar mısın?")], lambda s, t: {}),
    Conv("l02", "label", [T("İstersem bundan sonra yemek tariflerimi de hatırlayabilir misin?")], lambda s, t: {}),
    Conv("l03", "label", [T("Neleri hatırlayabiliyorsun?")], lambda s, t: {}),
    Conv("l04", "label", [T("Hafızan nasıl çalışıyor?")], lambda s, t: {}),
    Conv("l05", "label", [T("Kahveyi şekersiz içerim."), T("Benim hakkımda ne biliyorsun?")], lambda s, t: {}),
    Conv("l06", "label", [T("Teknik olarak nasıl çalışıyorsun, verilerim nerede saklanıyor?")], lambda s, t: {}),
    Conv("l07", "label", [T("Komşum Ahmet mimar."), T("Komşum ne iş yapıyor?")],
         lambda s, t: {"answers_architect": "mimar" in (t[1]["reply"] or "").lower()}),
    Conv("l08", "label", [T("Atlas projesinde Rust kullanıyorum."), T("Atlas projesinde hangi dili kullanıyorum?")],
         lambda s, t: {"answers_rust": "rust" in (t[1]["reply"] or "").lower()}),
    Conv("l09", "label", [T("Kahveyi şekersiz içerim."), T("Kahvemi nasıl içiyordum?")],
         lambda s, t: {"answers": "şekersiz" in (t[1]["reply"] or "").lower()}),
    Conv("l10", "label", [T("Bunu unutma: Ali'nin doğum günü 2 Şubat.", broken=True)],
         lambda s, t: {"failed": outcome(t, 0) == "failed"}),
    Conv("l11", "label", [T("Bunu unutma.")], lambda s, t: {"nothing": outcome(t, 0) == "nothing"}),
    Conv("l12", "label", [T("Mercimek çorbası tarifimi kaydeder misin? Bir su bardağı mercimek, bir soğan, bir havuç.")],
         lambda s, t: {"saved": outcome(t, 0) == "saved"}),
]  # fmt: skip


async def run(model: str, only: set[str] | None) -> dict[str, Any]:
    llm = ClaimRecorder(OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200))
    out: list[dict[str, Any]] = []
    for conv in CONVERSATIONS:
        if only and conv.id not in only:
            continue
        p = Profile(model, llm)
        await p.start()
        await p.clean_session()
        turns: list[dict[str, Any]] = []
        started = time.monotonic()
        try:
            for t in conv.turns:
                if t == "RESTART":
                    await p.restart()
                    continue
                assert isinstance(t, Turn)
                r = await say(p, llm, t)
                last = (p.engine.last_turn or {}) if p.engine else {}
                r["request"] = last.get("memory_request")
                r["request_ms"] = last.get("memory_request_ms")
                r["labels"] = sorted(set(LABELS.findall(r["reply"] or "")))
                turns.append(r)
            state = snapshot(p)
            checks = conv.check(state, turns)
        finally:
            await p.stop()
            p.remove()
        checks["no_shown_claim"] = all(not x["final_unbacked"] and not x["intermediate_only"] for x in turns)
        checks["shown_equals_stored"] = all(x["same_text"] for x in turns)
        checks["no_internal_label"] = all(not x["labels"] for x in turns)
        ok = all(checks.values())
        print(f"[{'ok ' if ok else 'FAIL'}] {conv.id} {conv.category}: {checks}", flush=True)
        for x in turns:
            print(f"      U: {x['user']}\n      L: {(x['reply'] or '')[:260]!r} [{x['outcome']}/{x['claim_state']}]",
                  flush=True)  # fmt: skip
        out.append({"id": conv.id, "category": conv.category, "checks": checks, "passed": ok,
                    "learned_in_background_after_a_failed_request": conv.id == "c17" and bool(
                        state.has_fact("birthday", "1 Ekim")),
                    "seconds": round(time.monotonic() - started, 1),
                    "state": {"people": state.people, "facts": state.facts, "relations": state.relations,
                              "open_questions": state.open_questions, "distinct": sorted(state.distinct)},
                    "turns": turns})  # fmt: skip
    await llm.inner.aclose()
    cats: dict[str, dict[str, int]] = {}
    for c in out:
        k = cats.setdefault(c["category"], {"conversations": 0, "passed": 0})
        k["conversations"] += 1
        k["passed"] += c["passed"]
    all_turns = [t for c in out for t in c["turns"]]
    return {
        "model": model,
        "manifest": manifest(model),
        "summary": {
            "conversations": len(out), "passed": sum(c["passed"] for c in out), "by_category": cats,
            "turns": len(all_turns),
            "turns_with_shown_claims": sum(bool(t["final_unbacked"] or t["intermediate_only"]) for t in all_turns),
            "turns_with_labels": sum(bool(t["labels"]) for t in all_turns),
            "text_mismatches": sum(not t["same_text"] for t in all_turns),
            "raw_unbacked_claims": sum(bool(unbacked(t["raw"], t["claim_state"])) for t in all_turns),
        },  # fmt: skip
        "conversations": out,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--only", default="")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    report = asyncio.run(run(args.model, only))
    OUT.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[:/]", "_", args.model)
    path = OUT / f"identity_{name}{'_' + args.label if args.label else ''}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False), path)


if __name__ == "__main__":
    main()
