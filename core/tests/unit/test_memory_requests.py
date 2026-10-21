"""Explicit memory requests (Phase 7.2): which messages start a save, what the stage-2 request
looks like, and how unusable model items are kept safe."""

from __future__ import annotations

import json

import pytest

from lazis.memory import commands, extraction
from lazis.memory.extraction import Target

SAVES = [
    # the brief's list
    "Bunu unutma.", "Şunu hafızana kaydet.", "Lütfen şunu not al: Murat'ın doğum günü 12 Haziran.",
    "Bunu not et.", "Aklında tut.", "Bunu hatırla.", "Şunu kaydet.",
    "Bu bilgiyi unutmanı istemiyorum.", "Bunu ileride hatırlamanı istiyorum.",
    "Not düş: kira her ayın beşinde.", "Şunu bilmeni istiyorum, unutma.",
    # polite and alternative forms
    "Not alır mısın: yarın saat 10'da toplantı var.", "Şunu not edebilir misin? Elif'in okulu 8'de başlıyor.",
    "Kaydeder misin, Ayşe'nin yeni adresi Kadıköy.", "Bunu kaydetmeni istiyorum.", "Kayda geçir: aidat 750 lira.",
    "Kayda al bunu: araba muayenesi aralıkta.", "Hafızana ekle: Burak'ın düğünü haziranda.",
    "Aklının bir köşesinde olsun: Zeynep çikolata sevmez.", "Bir kenara yaz: toplantı perşembeye kaldı.",
    "Unutmayın lütfen, annemin doğum günü 3 Mart.", "Hatırlayın: kızımın servisi 7.40'ta.",
    "Kaydını tut: su faturası ayın 20'sinde.", "Kayıt altına al: sigorta martta bitiyor.",
    "Aklında olsun, hafta sonu annemlere gideceğim.", "Aklında bulunsun: Can laktoz yemiyor.",
    "Bunu not etsene.", "Lütfen not alın: toplantı saat 3'te.", "Not ediniz: anahtar komşuda.",
    "Bunu bil: kahveyi şekersiz içerim.", "Unutmayasın, Murat'ın düğünü eylülde.",
    "Bunu bir kenara not et.", "Kaydetmelisin bunu: Ali'nin telefonu değişti.", "Şunu unutmamanı rica ediyorum: Selin vejetaryen.",
]  # fmt: skip
NOT_SAVES = [
    "Bana kısa bir toplantı notu hazırla.", "Not almak için hangi uygulamayı önerirsin?",
    "“Bunu not al” ifadesini İngilizceye çevir.", '"Lütfen şunu not al" cümlesi doğru mu yazılmış?',
    "Bunu kaydetme.", "Notlarımı nereye kaydetsem?", "Dosyayı kaydettim ama açılmıyor.",
    "Bunu kaydettin mi?", "Bunu kaydetmeliyim.", "Not defterimi kaybettim.", "Toplantıda not alıyordum.",
    "Not ortalamam 3.2.", "Hatırlıyor musun, geçen yaz İzmir'e gitmiştik?", "Anahtarlarımı unuttum.",
    "Ders notlarımı özetler misin?", "Notu 85 olan öğrenciler kimler?", "Bugün çok yorgunum.",
    "Bu notayı nasıl çalarım?", "Kayıt olmak için ne gerekiyor?", "Not yazmayı sevmem.",
]  # fmt: skip


@pytest.mark.parametrize("message", SAVES)
def test_requests_that_start_a_save(message: str) -> None:
    assert commands.detect(message) == "remember"


@pytest.mark.parametrize("message", NOT_SAVES)
def test_other_uses_of_not_and_kaydet(message: str) -> None:
    assert commands.detect(message) in (None, "recall")


def test_forget_is_still_forget() -> None:
    assert commands.detect("Bunu unutmanı istiyorum.") == "forget"
    assert commands.detect("Ahmet'in mesleğini unut.") == "forget"


@pytest.mark.parametrize(
    ("message", "bare"),
    [("Bunu unutma.", True), ("Bunu unutma lütfen!", True), ("Tamam, bunu not al.", True),
     ("Aklında tut bunu efendim.", True), ("Lütfen bunu kaydet.", True),
     ("Bunu unutma: Ahmet 5 Mayıs'ta doğdu.", False), ("Lütfen şunu not al: Burak'ın düğünü haziranda.", False),
     ("Not al, kira beşinde.", False)],
)  # fmt: skip
def test_a_bare_request_points_to_the_previous_message(message: str, bare: bool) -> None:
    assert commands.cue_only(message) is bare


# ----- stage 2: the same instruction as learning, with the request stated -------------------
class _Ctx:
    known: tuple[()] = ()
    user_facts: tuple[()] = ()
    forgotten: tuple[()] = ()
    questions: tuple[()] = ()


def test_the_remember_instruction_is_the_learning_one_with_the_request() -> None:
    text = commands.remember_instruction("Lütfen şunu not al: Burak'ın düğünü haziranda.", _Ctx())
    assert text.startswith(extraction.RULES)  # the rules measured on the gold set
    assert (
        commands.REMEMBER_NOTE in text
        and "«Lütfen şunu not al: Burak'ın düğünü haziranda.»" in text
    )
    previous = commands.remember_instruction("Ahmet'in doğum günü 5 Mayıs.", _Ctx(), previous=True)
    assert commands.REMEMBER_PREVIOUS_NOTE in previous and commands.REMEMBER_NOTE not in previous


def test_the_remember_schema_asks_for_the_action_first() -> None:
    schema = commands.remember_schema()
    assert list(schema["properties"])[:3] == ["action", "items", "relations"]
    assert schema["properties"]["action"]["enum"] == ["none", "remember"]


@pytest.mark.parametrize(
    ("raw", "action", "items"),
    [('{"action": "remember", "items": [{"message": "m1"}], "relations": []}', "remember", 1),
     ('{"action": "none", "items": [], "relations": []}', "none", 0),
     ('{"action": "forget", "items": []}', None, 0), ("bozuk", None, 0)],
)  # fmt: skip
def test_parse_remember(raw: str, action: str | None, items: int) -> None:
    cmd = commands.parse_remember(raw)
    assert (cmd.action if cmd else None) == action
    assert (len(cmd.items) if cmd else 0) == items


# ----- validation: a thing is never one of the user's own facts --------------------------------
def _item(entity: str, predicate: str, value: str, statement: str, quote: str) -> dict[str, object]:
    return {"message": "m1", "quote": quote, "entity": entity, "relation": "", "predicate": predicate,
            "value": value, "statement": statement, "change": False, "replaces": "", "certain": True,
            "sensitive": "", "importance": 0.8}  # fmt: skip


@pytest.mark.parametrize(
    ("message", "item_", "predicate", "about"),
    [
        # Phase 7.2 real-model cases: written as the user's birthday and technology before
        ("Bunu not et: arabanın sigortası mart ayında bitiyor.",
         _item("araba sigortası", "birthday", "mart", "Arabanın sigortası mart ayında bitiyor.",
               "arabanın sigortası mart ayında bitiyor"), "note", "user"),
        ("Not al: kira her ayın beşinde ödeniyor.",
         _item("kira", "technology", "her ayın beşinde ödeniyor", "Kira her ayın beşinde ödeniyor.",
               "kira her ayın beşinde ödeniyor"), "note", "user"),
        ("Unutma, doğum günü 5 Mayıs.",
         _item("", "birthday", "5 Mayıs", "Doğum günü 5 Mayıs.", "doğum günü 5 Mayıs"), "note", "user"),
        # the user in the message: kept as said
        ("Bunu unutma: doğum günüm 5 Mayıs.",
         _item("", "birthday", "5 Mayıs", "Kullanıcının doğum günü 5 Mayıs.", "doğum günüm 5 Mayıs"),
         "birthday", "user"),
        ("Adım Kerem, unutma.", _item("", "preferred_name", "Kerem", "Kullanıcının adı Kerem.", "Adım Kerem"),
         "preferred_name", "user"),
        ("Murat'ın doğum günü 12 Haziran, not al.",
         _item("Murat", "birthday", "12 Haziran", "Murat'ın doğum günü 12 Haziran.",
               "Murat'ın doğum günü 12 Haziran"), "birthday", "entity"),
    ],
)  # fmt: skip
def test_things_are_not_the_users_facts(
    message: str, item_: dict[str, object], predicate: str, about: str
) -> None:
    out = extraction.validate([item_], [Target("m1", "id", message)])
    assert [(e.candidate.predicate, e.candidate.about) for e in out.accepted] == [
        (predicate, about)
    ]


def test_notices_carry_no_technical_wording() -> None:
    failed = commands.Outcome("failed").notice()
    assert (
        "teknik bir hata nedeniyle" not in failed and "Bunu şu anda kaydedemedim efendim" in failed
    )
    assert "veritabanı" not in commands.Outcome("saved", ["x"]).notice()
    assert (
        json.dumps(commands.Outcome("cancelled").notice(), ensure_ascii=False).count("iptal") == 1
    )
