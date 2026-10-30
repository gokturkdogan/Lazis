"""Phase 9.1 with the real model: memory operations that agree with the database (production
engine, synthetic data, throwaway encrypted profiles — a temp dir and a random key, no Keychain).

    uv run --project core python evals/runners/p91_memory_ops.py --model gemma4:12b-it-qat
    uv run --project core python evals/runners/p91_memory_ops.py --only delete --label d1

Groups (each conversation on a fresh profile):

* ``request`` (20) — explicit saves that succeed, fail (the command model's answer corrupted),
  are refused, wait for "which Ahmet?", are cancelled, or are asked about afterwards
  ("Az önce kaydettin mi?");
* ``field`` (20) — what field a fact lands in (age, workplace, city, a relative's city and
  job, a preference, the past; "Atlas" as a workplace, a restaurant and a friend);
* ``time`` (20) — jobs, workplaces and cities over time (a change, two jobs at once, leaving,
  starting, "hâlâ", a vague time, a friend who stopped);
* ``delete`` (20) — forgetting from chat ("Kahve bilgimi sil", "Telefon bilgimi unut", the old
  or current workplace, a relative's city, several records on one topic, an unclear or a
  missing target, nothing learned again);
* ``repeat`` — the critical conversations again (three more generations each).

Every check reads the database after the turn (learning settled), never only the reply; the
reply checks are the Phase 9 independent word lists (claims, internal layers, shown = stored).
Writes evals/reports/phase9/memory_ops_<model>[_<label>].json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from common import manifest
from p6_sessions import Profile
from p9_guards import T, GuardRecorder, say

from lazis.memory import claims
from lazis.memory import repository as memory_repo
from lazis.providers.llm.ollama import OllamaProvider

OUT = Path(__file__).resolve().parents[1] / "reports" / "phase9"

State = dict[str, Any]
Check = Callable[[list[State]], dict[str, bool]]


def full_state(p: Profile) -> State:
    def read(c: Any) -> State:
        mems = []
        for m in memory_repo.list_memories(c, status=None, limit=1000):
            e = memory_repo.get_entity(c, m.subject_id) if m.subject_id else None
            mems.append({"about": e.name if e else "user", "predicate": m.predicate, "value": m.value,
                         "status": m.status, "origin": m.origin, "content": m.content})  # fmt: skip
        rels = []
        for r in c.execute("SELECT source_id, type, target_id, status FROM memory_relationships"):
            a, b = memory_repo.get_entity(c, r[0]), memory_repo.get_entity(c, r[2])
            rels.append({"source": a.name if a else "user", "type": r[1],
                         "target": b.name if b else "user", "status": r[3]})  # fmt: skip
        inbox = [
            {"type": i.type, "summary": i.summary} for i in memory_repo.list_inbox(c, status="open")
        ]
        return {"memories": mems, "relationships": rels, "inbox": inbox}

    return p.q(read)


def f(s: str) -> str:
    return claims.fold(s)


def rows(st: State, about: str = "user", predicate: str | None = None, value: str = "",
         status: str | None = "active") -> list[dict[str, Any]]:  # fmt: skip
    return [m for m in st["memories"] if m["about"] == about and (predicate is None or m["predicate"] == predicate)
            and f(value) in f(m["value"] + " " + m["content"]) and (status is None or m["status"] == status)]  # fmt: skip


def has(
    st: State, about: str, predicate: str | None, value: str = "", status: str = "active"
) -> bool:
    return bool(rows(st, about, predicate, value, status))


def nothing_about(st: State, value: str) -> bool:
    return not any(f(value) in f(m["value"] + " " + m["content"]) for m in st["memories"])


AFFIRM = re.compile(r"^\W*(evet|elbette|tabii|tabi|kesinlikle)\b")


def affirms(reply: str) -> bool:
    return bool(AFFIRM.search(f(reply or "")))


def denies(reply: str) -> bool:
    r = f(reply or "")
    return bool(
        re.search(
            r"\b(hayir|kaydedemedim|kaydetmedim|kaydedilmedi|yazilmadi|henuz|kaydedemedi|kayitli degil|bulunmuyor)",
            r,
        )
    )


@dataclass
class Conv:
    cid: str
    group: str
    turns: list[T]
    check: Check
    note: str = ""
    seed_ok: bool = True  # earlier turns only set the scene (their reply is still checked)


def C(cid: str, group: str, msgs: list[str | T], check: Check, note: str = "") -> Conv:
    return Conv(cid, group, [m if isinstance(m, T) else T(m) for m in msgs], check, note)


def last(ts: list[State]) -> State:
    return ts[-1]


AHMETS = "İki Ahmet tanıyorum: biri komşum Ahmet, diğeri iş arkadaşım Ahmet."
BDAY = "Bunu unutma: Ahmet'in doğum günü 5 Mayıs."
KERVAN = "Kervan'da çalışıyorum."
DEV = "Yazılım geliştiricisiyim."

REQUEST = [
    C("a01", "request", ["Atlas şirketinde çalıştığımı hafızana kaydet."],
      lambda t: {"saved_as_employer": has(last(t), "user", "employer", "Atlas"),
                 "not_a_city": not has(last(t), "user", "location", "Atlas")}),
    C("a02", "request", [T("Atlas şirketinde çalıştığımı hafızana kaydet.", broken=True)],
      lambda t: {"nothing_written": nothing_about(last(t), "Atlas")}, "failed"),
    C("a03", "request", [T("Bunu unutma: köpeğimin veterineri Dr. Selin.", broken=True), "Az önce kaydettin mi?"],
      lambda t: {"nothing_written": nothing_about(last(t), "Selin"),
                 "reply_not_yes": not affirms(t[-1]["reply"]), "reply_says_no": denies(t[-1]["reply"])}, "failed + asked"),
    C("a04", "request", [T("Atlas'ta çalıştığımı kaydet. Ayrıca en sevdiğim renk yeşil.", broken=True)],
      lambda t: {"atlas_not_written": nothing_about(last(t), "Atlas")}, "failed, two facts"),
    C("a05", "request", ["Bunu kaydet: banka şifrem 4471."],
      lambda t: {"nothing_written": nothing_about(last(t), "4471"), "not_repeated": "4471" not in (t[-1]["reply"] or "")}),
    C("a06", "request", ["Köpeğimin veterineri Dr. Selin.", T("Bunu unutma.", broken=True)],
      lambda t: {"kept_from_statement": has(last(t), "user", None, "Selin") or any(
          has(last(t), m["about"], None, "Selin") for m in last(t)["memories"]),
                 "reply_not_failed": t[-1]["outcome"] == "saved"}, "bare request failed, fact known"),
    C("a07", "request", ["Lütfen şunu not al."], lambda t: {"nothing_written": not last(t)["memories"]}),
    C("a08", "request", [T("Bunu unutma: anahtarlar mutfak çekmecesinde.", stop_after=12)],
      lambda t: {"saved_stays": has(last(t), "user", None, "çekmece")}, "stopped mid-reply after the save"),
    C("a09", "request", [AHMETS, BDAY],
      lambda t: {"waits": not any(m["predicate"] == "birthday" for m in last(t)["memories"])}, "which Ahmet?"),
    C("a10", "request", [AHMETS, BDAY, "Vazgeç, kaydetme."],
      lambda t: {"never_written": not any(m["predicate"] == "birthday" for m in last(t)["memories"])}, "cancelled"),
    C("a11", "request", [AHMETS, BDAY, "Komşum olan."],
      lambda t: {"written_once": len([m for m in last(t)["memories"] if m["predicate"] == "birthday"]) == 1}, "answered"),
    C("a12", "request", [KERVAN, T("Kervan bilgisini düzelt: Atlas'tayım.", broken=True)],
      lambda t: {"kervan_current": has(last(t), "user", "employer", "Kervan"),
                 "atlas_not_written": nothing_about(last(t), "Atlas")}, "failed correction (f06)"),
    C("a13", "request", [KERVAN, "Kervan bilgisini düzelt: Atlas'tayım."],
      lambda t: {"atlas_current": has(last(t), "user", "employer", "Atlas"),
                 "kervan_not_current": not has(last(t), "user", "employer", "Kervan"),
                 "atlas_not_a_city": not has(last(t), "user", "location", "Atlas")}, "correction"),
    C("a14", "request", ["Not al: kira her ayın beşinde ödeniyor."],
      lambda t: {"saved": has(last(t), "user", None, "beş")}),
    C("a15", "request", ["Telefonum Pixel 8.", "Telefon bilgimi unut.", "Telefonumla ilgili ne biliyorsun?"],
      lambda t: {"gone": nothing_about(last(t), "Pixel")}, "forgotten, asked"),
    C("a16", "request", ["Bunu hafızana alma, sadece söylüyorum: yarın işe geç gideceğim."],
      lambda t: {"nothing_written": not last(t)["memories"]}),
    C("a17", "request", [T("Bunu unutma: Atlas'ta çalışıyorum.", broken=True), "Atlas'ta çalışıyorum."],
      lambda t: {"first_not_written": nothing_about(t[0], "Atlas"),
                 "said_again_learned": has(last(t), "user", "employer", "Atlas")}, "failed, then said plainly"),
    C("a18", "request", ["Bunu unutma: dişçi randevum salı saat üçte.", "Kaydettin mi?"],
      lambda t: {"saved": has(last(t), "user", None, "dişçi"), "reply_not_no": not re.search(
          r"\b(hayir|kaydedemedim|kaydetmedim)\b", f(t[-1]["reply"] or ""))}, "saved + asked"),
    C("a19", "request", [T("Hafızana kaydet: Pamuk'un aşı günü 20 Kasım.", broken=True), "Kaydettin mi?"],
      lambda t: {"nothing_written": nothing_about(last(t), "20 Kasım"), "reply_not_yes": not affirms(t[-1]["reply"])},
      "failed + asked"),
    C("a20", "request", [T("Şunu kaydet: Elif'in yeni telefonu Pixel.", broken=True)],
      lambda t: {"nothing_written": nothing_about(last(t), "Pixel")}, "failed"),
]  # fmt: skip


def no_family(st: State) -> bool:
    return not any(m["predicate"] == "family" for m in st["memories"])


FIELD = [
    C("b01", "field", ["29 yaşındayım."], lambda t: {"age": has(last(t), "user", "age", "29"), "not_family": no_family(last(t))}),
    C("b02", "field", ["Atlas'ta çalışıyorum."], lambda t: {"employer": has(last(t), "user", "employer", "Atlas"),
                                                           "not_city": not has(last(t), "user", "location", "Atlas")}),
    C("b03", "field", ["İstanbul'da yaşıyorum."], lambda t: {"city": has(last(t), "user", "location", "İstanbul")}),
    C("b04", "field", ["Kardeşim Elif İzmir'de yaşıyor."],
      lambda t: {"elif_city": has(last(t), "Elif", "location", "İzmir"), "not_family": no_family(last(t)),
                 "not_users_city": not has(last(t), "user", "location", "İzmir")}),
    C("b05", "field", ["Annem öğretmen."], lambda t: {"not_users_job": not has(last(t), "user", "occupation", "öğretmen"),
                                                     "kept": has(last(t), "user", None, "öğretmen") or any(
                                                         "ogretmen" in f(m["value"]) for m in last(t)["memories"])}),
    C("b06", "field", ["En sevdiğim renk yeşil."], lambda t: {"preference": any(
        m["predicate"] in ("likes", "interest") and "yesil" in f(m["value"]) for m in last(t)["memories"])}),
    C("b07", "field", ["Eskiden Kervan'da çalışıyordum."],
      lambda t: {"past": has(last(t), "user", "employer", "Kervan", "superseded"),
                 "not_current": not has(last(t), "user", "employer", "Kervan")}),
    C("b08", "field", ["Dün Atlas adlı restorana gittim."],
      lambda t: {"not_employer": not has(last(t), "user", "employer", "Atlas"),
                 "not_a_home": not any(m["predicate"] == "location" for m in last(t)["memories"])}),
    C("b09", "field", ["Atlas adında bir arkadaşım var."],
      lambda t: {"not_employer": not has(last(t), "user", "employer", "Atlas"),
                 "not_a_city": not any(m["predicate"] == "location" for m in last(t)["memories"])}),
    C("b10", "field", ["Kız kardeşim Ece Bursa'da yaşıyor."],
      lambda t: {"ece_city": has(last(t), "Ece", "location", "Bursa"), "not_family": no_family(last(t))}),
    C("b11", "field", ["Babam emekli bir mühendis."],
      lambda t: {"not_users_job": not has(last(t), "user", "occupation", "mühendis")}),
    C("b12", "field", ["Ahmet 40 yaşında."], lambda t: {"not_family": no_family(last(t)),
                                                       "not_users_age": not has(last(t), "user", "age")}),
    C("b13", "field", ["Kuzenim Can Ankara'da avukat."],
      lambda t: {"cans_job": has(last(t), "Can", "occupation", "avukat"),
                 "not_users_job": not has(last(t), "user", "occupation", "avukat")}),
    C("b14", "field", [DEV], lambda t: {"job": has(last(t), "user", "occupation", "geliştirici")}),
    C("b15", "field", ["Kahveyi şekersiz içerim."], lambda t: {"not_family": no_family(last(t)), "kept": any(
        "kahve" in f(m["value"]) for m in last(t)["memories"])}),
    C("b16", "field", ["Telefonum Pixel 8."], lambda t: {"phone": has(last(t), "user", "phone", "Pixel")}),
    C("b17", "field", ["Eşim Zeynep hemşire."], lambda t: {"zeyneps_job": has(last(t), "Zeynep", "occupation", "hemşire"),
                                                          "not_users_job": not has(last(t), "user", "occupation", "hemşire")}),
    C("b18", "field", ["İzmir'de çalışıyorum."], lambda t: {"not_a_home": not has(last(t), "user", "location", "İzmir")}),
    C("b19", "field", ["Oğlum Efe 8 yaşında."], lambda t: {"not_users_age": not has(last(t), "user", "age"),
                                                          "not_family_age": not any(m["predicate"] == "family" and "8" in m["value"]
                                                                                    and m["about"] == "Efe" for m in last(t)["memories"])}),
    C("b20", "field", ["Hâlâ Ankara'da yaşıyorum."], lambda t: {"city": has(last(t), "user", "location", "Ankara")}),
]  # fmt: skip


def cur(st: State, about: str, pred: str, value: str) -> bool:
    return has(st, about, pred, value, "active")


def past(st: State, about: str, pred: str, value: str) -> bool:
    return has(st, about, pred, value, "superseded")


TIME = [
    C("t01", "time", [DEV, "Artık ürün yöneticisi olarak çalışıyorum."],
      lambda t: {"new_current": cur(last(t), "user", "occupation", "ürün"), "old_past": past(last(t), "user", "occupation", "geliştirici"),
                 "old_not_current": not cur(last(t), "user", "occupation", "geliştirici")}),
    C("t02", "time", [DEV, "Yazılım geliştiriciliğini bıraktım, artık ürün yöneticisiyim."],
      lambda t: {"new_current": cur(last(t), "user", "occupation", "ürün"),
                 "old_not_current": not cur(last(t), "user", "occupation", "geliştirici")}),
    C("t03", "time", ["Yazılım geliştiricisiyim, ayrıca eğitmenlik yapıyorum."],
      lambda t: {"both_current": cur(last(t), "user", "occupation", "geliştirici") and cur(last(t), "user", "occupation", "eğitmen")}),
    C("t04", "time", [DEV, "Eğitmenlik de yapıyorum."],
      lambda t: {"first_still_current": cur(last(t), "user", "occupation", "geliştirici"),
                 "first_not_past": not past(last(t), "user", "occupation", "geliştirici")}),
    C("t05", "time", ["Arkadaşım Ahmet yazılım geliştiricisi.", "Ahmet artık yazılım geliştirmiyor, kendi restoranını açtı."],
      lambda t: {"no_developer_current": not cur(last(t), "Ahmet", "occupation", "geliştirici"),
                 "developer_history": past(last(t), "Ahmet", "occupation", "geliştirici")}, "Phase 6 3.memory"),
    C("t06", "time", [KERVAN, "Kervan'dan ayrıldım."], lambda t: {"kervan_not_current": not cur(last(t), "user", "employer", "Kervan")}),
    C("t07", "time", [KERVAN, "Atlas'ta işe başladım."],
      lambda t: {"atlas_current": cur(last(t), "user", "employer", "Atlas"), "kervan_not_current": not cur(last(t), "user", "employer", "Kervan")}),
    C("t08", "time", ["Eskiden Kervan'da çalışıyordum, artık Atlas'ta çalışıyorum."],
      lambda t: {"atlas_current": cur(last(t), "user", "employer", "Atlas"), "kervan_past": past(last(t), "user", "employer", "Kervan"),
                 "kervan_not_current": not cur(last(t), "user", "employer", "Kervan")}),
    C("t09", "time", [KERVAN, "Hâlâ Kervan'da çalışıyorum."],
      lambda t: {"kervan_current": cur(last(t), "user", "employer", "Kervan"),
                 "one_record": len(rows(last(t), "user", "employer", "Kervan", None)) == 1}),
    C("t10", "time", [DEV, "Eskiden öğretmendim."],
      lambda t: {"dev_current": cur(last(t), "user", "occupation", "geliştirici"), "teacher_not_current": not cur(last(t), "user", "occupation", "öğretmen")}),
    C("t11", "time", ["Ankara'da yaşıyorum.", "Artık İzmir'de yaşıyorum."],
      lambda t: {"izmir_current": cur(last(t), "user", "location", "İzmir"), "ankara_not_current": not cur(last(t), "user", "location", "Ankara")}),
    C("t12", "time", ["Ankara'da yaşıyorum.", "Önceden İstanbul'da yaşıyordum."],
      lambda t: {"ankara_current": cur(last(t), "user", "location", "Ankara"), "istanbul_not_current": not cur(last(t), "user", "location", "İstanbul")}),
    C("t13", "time", [DEV, "Öğretmenim."], lambda t: {"dev_not_replaced_unasked": cur(last(t), "user", "occupation", "geliştirici")
                                                      or bool(last(t)["inbox"])}),
    C("t14", "time", ["34 yaşındayım.", "Benim hakkımda bildiklerini güncelle: 35 yaşındayım."],
      lambda t: {"35_current": cur(last(t), "user", "age", "35"), "34_not_current": not cur(last(t), "user", "age", "34"),
                 "not_family": no_family(last(t))}),
    C("t15", "time", ["Komşum Ahmet doktor.", "Ahmet doktorluğu bıraktı."],
      lambda t: {"not_doctor_now": not cur(last(t), "Ahmet", "occupation", "doktor")}),
    C("t16", "time", [DEV, "Ürün yöneticisi görevine geçtim."],
      lambda t: {"new_current": cur(last(t), "user", "occupation", "ürün"), "old_not_current": not cur(last(t), "user", "occupation", "geliştirici")}),
    C("t17", "time", ["Elif Kervan'da çalışıyor.", "Elif Kervan'dan ayrıldı, artık Atlas'ta çalışıyor."],
      lambda t: {"elif_atlas": cur(last(t), "Elif", "employer", "Atlas") or any(
          r["source"] == "Elif" and r["target"] == "Atlas" and r["status"] == "active" for r in last(t)["relationships"]),
                 "elif_not_kervan": not cur(last(t), "Elif", "employer", "Kervan") and not any(
          r["source"] == "Elif" and r["target"] == "Kervan" and r["status"] == "active" for r in last(t)["relationships"])}),
    C("t18", "time", ["Muhasebeciyim.", "Muhasebeciliği bıraktım."], lambda t: {"not_current": not cur(last(t), "user", "occupation", "muhasebe")}),
    C("t19", "time", [KERVAN, "Kervan'da değil, Atlas'ta çalışıyorum."],
      lambda t: {"atlas_current": cur(last(t), "user", "employer", "Atlas"), "kervan_not_current": not cur(last(t), "user", "employer", "Kervan")}),
    C("t20", "time", [DEV, "Bir ara öğretmenlik yaptım galiba."],
      lambda t: {"dev_current": cur(last(t), "user", "occupation", "geliştirici"), "teacher_not_current": not cur(last(t), "user", "occupation", "öğretmen")}),
]  # fmt: skip


def gone(st: State, value: str) -> bool:
    return nothing_about(st, value)


def coffees(st: State) -> list[dict[str, Any]]:
    return [
        m
        for m in st["memories"]
        if "kahve" in f(m["value"] + " " + m["content"]) and m["status"] == "active"
    ]


def d10(t: list[State]) -> dict[str, bool]:
    seeded = coffees(t[0])
    if len(seeded) >= 2:  # several records: asked, nothing deleted on a guess
        return {
            "asked": t[-1]["outcome"] == "ambiguous",
            "nothing_deleted": len(coffees(last(t))) == len(seeded),
        }
    return {"deleted": gone(last(t), "kahve")}


def d16(t: list[State]) -> dict[str, bool]:
    """The user named two Ahmets (one may still wait for "which Ahmet?"): deleting either one's
    job is a guess. Run 1 passed this on a too lenient check; corrected after hand reading."""
    def jobs(st: State) -> int:
        return len([m for m in st["memories"] if m["predicate"] == "occupation" and m["about"] == "Ahmet"])

    return {"nothing_deleted": jobs(last(t)) == jobs(t[1]), "asked": t[-1]["outcome"] == "ambiguous"}


DELETE = [
    C("d01", "delete", ["Kahveyi şekersiz içerim.", "Kahve bilgimi sil."], lambda t: {"deleted": gone(last(t), "kahve")}),
    C("d02", "delete", ["Kahvemi sütsüz içerim.", "Kahve tercihimle ilgili bilgiyi sil."], lambda t: {"deleted": gone(last(t), "kahve")}),
    C("d03", "delete", ["Filtre kahveyi severim.", "Kahve hakkındaki kaydını unut."], lambda t: {"deleted": gone(last(t), "kahve")}),
    C("d04", "delete", ["Telefonum Pixel 8.", "Telefon bilgimi unut."], lambda t: {"deleted": gone(last(t), "Pixel")}),
    C("d05", "delete", ["iPhone 15 kullanıyorum.", "Telefon modelimi hafızandan kaldır."], lambda t: {"deleted": gone(last(t), "iPhone")}),
    C("d06", "delete", ["Eskiden Kervan'da çalışıyordum, artık Atlas'ta çalışıyorum.", "Eski işyerimle ilgili bilgiyi sil."],
      lambda t: {"old_deleted": gone(last(t), "Kervan"), "current_kept": has(last(t), "user", None, "Atlas")}),
    C("d07", "delete", ["Eskiden Kervan'da çalışıyordum, artık Atlas'ta çalışıyorum.", "Güncel işyeri bilgimi sil."],
      lambda t: {"current_deleted": gone(last(t), "Atlas"), "old_kept": has(last(t), "user", None, "Kervan", "superseded")}),
    C("d08", "delete", ["İstanbul'da yaşıyorum.", "İstanbul'da yaşadığım bilgisini unut."], lambda t: {"deleted": gone(last(t), "İstanbul")}),
    C("d09", "delete", ["Kardeşim Elif İzmir'de yaşıyor.", "Elif'in nerede yaşadığını unut."], lambda t: {"deleted": gone(last(t), "İzmir")}),
    C("d10", "delete", ["Kahveyi şekersiz içerim. Filtre kahveyi de severim.", "Kahve bilgimi sil."], d10,
      "several on one topic"),
    C("d11", "delete", ["Kahveyi şekersiz içerim. Filtre kahveyi de severim.", "Şekersiz kahve bilgimi sil."],
      lambda t: {"that_one": gone(last(t), "şekersiz"), "other_kept": not gone(last(t), "filtre")
                 or not any("filtre" in f(m["value"]) for m in t[0]["memories"])}),
    C("d12", "delete", ["Kahveyi şekersiz içerim.", "Şunu sil."], lambda t: {"nothing_deleted": not gone(last(t), "kahve")}),
    C("d13", "delete", ["Telefonum Pixel 8.", "Araba bilgimi sil."],
      lambda t: {"nothing_deleted": not gone(last(t), "Pixel"), "said_not_found": t[-1]["outcome"] == "not_found"}),
    C("d14", "delete", ["Telefonum Pixel 8.", "Telefon bilgimi unut.", "Telefonum neydi?"], lambda t: {"deleted": gone(last(t), "Pixel")}),
    C("d15", "delete", ["Arkadaşım Ahmet Ankara'da yaşıyor.", "Ahmet'in yaşadığı şehri unut."],
      lambda t: {"deleted": not has(last(t), "Ahmet", "location", "Ankara", None)}),
    C("d16", "delete", ["Arkadaşım Ahmet mimar.", "Komşum Ahmet doktor.", "Ahmet'in mesleğini unut."], d16,
      "two Ahmets"),
    C("d17", "delete", ["Telefonum Pixel 8.", "Elif'in telefonunu sil."], lambda t: {"users_phone_kept": not gone(last(t), "Pixel")}),
    C("d18", "delete", ["Kahveyi şekersiz içerim.", "Kahveyle ilgili tüm bilgileri sil."], lambda t: {"deleted": gone(last(t), "kahve")}),
    C("d19", "delete", ["Telefonum Pixel 8. İstanbul'da yaşıyorum.", "Telefon bilgimi unut."],
      lambda t: {"deleted": gone(last(t), "Pixel"), "city_kept": has(last(t), "user", "location", "İstanbul")}),
    C("d20", "delete", ["Komşum Ahmet doktor.", "Ahmet'in mesleği hakkındaki bilgileri unut."],
      lambda t: {"deleted": not has(last(t), "Ahmet", "occupation", None, None)}),
]  # fmt: skip

CRITICAL = {"a02", "a03", "a12", "b01", "b04", "t05", "t14", "d01", "d04", "d06"}
REPEAT = [Conv(f"{c.cid}r{n}", "repeat", c.turns, c.check, f"repeat of {c.cid}")
          for c in REQUEST + FIELD + TIME + DELETE if c.cid in CRITICAL for n in (2, 3, 4)]  # fmt: skip
GROUPS = {"request": REQUEST, "field": FIELD, "time": TIME, "delete": DELETE, "repeat": REPEAT}


async def run(model: str, only: set[str] | None) -> dict[str, Any]:
    llm = GuardRecorder(
        OllamaProvider(first_token_timeout=600, idle_timeout=120, max_duration=1200)
    )
    convs: list[dict[str, Any]] = []
    try:
        for group, items in GROUPS.items():
            if only and group not in only:
                continue
            for conv in items:
                p = Profile(model, llm)
                await p.start()
                await p.clean_session()
                out: list[dict[str, Any]] = []
                states: list[State] = []
                try:
                    for t in conv.turns:
                        r = await say(p, llm, t)
                        assert p.engine is not None
                        r["learning"] = dict(p.engine.learner.status)  # counts and durations only
                        st = full_state(p)
                        r["state"] = st
                        r["reply"] = r["done"] if r["done"] is not None else r["shown"]
                        out.append(r)
                        states.append(st)
                    checks = conv.check([{**st, "reply": r["reply"], "outcome": r["outcome"]}
                                         for r, st in zip(out, states, strict=True)])  # fmt: skip
                except Exception as exc:  # recorded, never hidden
                    checks = {"error": False}
                    out.append({"error": repr(exc)})
                finally:
                    await p.stop()
                    p.remove()
                guard = {
                    "shown_claims": sum(bool(r.get("shown_claims")) for r in out),
                    "shown_internal": sum(bool(r.get("shown_internal")) for r in out),
                    "text_mismatches": sum(not r.get("same_text", True) for r in out),
                    "early_only": sum(bool(r.get("early_only")) for r in out),
                }
                ok = all(checks.values())
                print(
                    f"[{'ok  ' if ok and not any(guard.values()) else 'FAIL'}] {conv.cid} {group} {checks} guard={guard}",
                    flush=True,
                )
                for r in out:
                    if "error" in r:
                        print(f"      ERROR {r['error']}")
                        continue
                    added = [
                        (m["about"], m["predicate"], m["value"], m["status"])
                        for m in r["state"]["memories"]
                    ]
                    print(f"      U: {r['user']}\n      outcome={r['outcome']} state={r['claim_state']}\n"
                          f"      L: {(r['reply'] or '')[:260]!r}\n      DB: {added}", flush=True)  # fmt: skip
                convs.append({"cid": conv.cid, "group": group, "note": conv.note, "checks": checks, "ok": ok,
                              "guard": guard, "turns": out})  # fmt: skip
    finally:
        await llm.inner.aclose()
    summary: dict[str, Any] = {}
    for g in GROUPS:
        cs = [c for c in convs if c["group"] == g]
        if cs:
            summary[g] = {"conversations": len(cs), "passed": sum(c["ok"] for c in cs),
                          "turns": sum(len(c["turns"]) for c in cs),
                          **{k: sum(c["guard"][k] for c in cs) for k in ("shown_claims", "shown_internal",
                                                                          "text_mismatches", "early_only")}}  # fmt: skip
    return {"model": model, "manifest": manifest(model), "summary": summary, "conversations": convs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="gemma4:12b-it-qat")
    ap.add_argument("--only", default="")
    ap.add_argument("--label", default="")
    args = ap.parse_args()
    only = {g for g in args.only.split(",") if g} or None
    report = asyncio.run(run(args.model, only))
    OUT.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[:/]", "_", args.model)
    path = OUT / f"memory_ops_{name}{'_' + args.label if args.label else ''}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False), path)


if __name__ == "__main__":
    main()
