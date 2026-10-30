"""The field fits the meaning (Phase 9.1): an age is not family, a sister's city is a city, a
workplace is not a city, a visit is not where one lives. The model's proposals here are the
ones real Gemma runs wrote (evals/reports/phase9, Phase 9.1 stage A); synthetic data only."""

from __future__ import annotations

from typing import Any

import pytest

from lazis.memory import extraction
from lazis.memory.extraction import Target


def proposal(quote: str, predicate: str, value: str, statement: str, entity: str = "",
             relation: str = "") -> dict[str, Any]:  # fmt: skip
    return {"message": "m1", "quote": quote, "entity": entity, "relation": relation,
            "predicate": predicate, "value": value, "statement": statement, "change": False,
            "replaces": "", "certain": True, "sensitive": "", "importance": 0.8}  # fmt: skip


def written(message: str, item: dict[str, Any]) -> list[tuple[str, str, str]]:
    checked = extraction.validate([item], [Target("m1", "msg", message)])
    return [(e.candidate.predicate, e.candidate.value,
             e.candidate.entity.name if e.candidate.entity else "user") for e in checked.accepted]  # fmt: skip


@pytest.mark.parametrize(
    ("message", "item", "expected"),
    [
        # Age (real: family "29 yaşında", family "35").
        ("29 yaşındayım.", proposal("29 yaşındayım.", "family", "29 yaşında", "Kullanıcı 29 yaşındadır."),
         [("age", "29", "user")]),
        ("Benim hakkımda bildiklerini güncelle: 35 yaşındayım.",
         proposal("35 yaşındayım", "family", "35", "Kullanıcı 35 yaşındadır."), [("age", "35", "user")]),
        ("Ahmet 40 yaşında.", proposal("Ahmet 40 yaşında", "note", "40 yaşında", "Ahmet 40 yaşında.", "Ahmet"),
         [("age", "40", "Ahmet")]),
        # A relative's age stays the relative's ("annem" has no name: family, as before).
        ("Annem 60 yaşında.", proposal("Annem 60 yaşında", "family", "annesi 60 yaşında",
                                       "Kullanıcının annesi 60 yaşında."),
         [("family", "annesi 60 yaşında", "user")]),
        # Someone's city (real: family "Bursa'da yaşıyor", family "İzmir").
        ("Kız kardeşim Ece Bursa'da yaşıyor.",
         proposal("Kız kardeşim Ece Bursa'da yaşıyor.", "family", "Bursa'da yaşıyor", "Ece Bursa'da yaşıyor.",
                  "Ece", "kız kardeşi"), [("location", "Bursa", "Ece")]),
        ("Kardeşim Elif İzmir'de yaşıyor.",
         proposal("Elif İzmir'de yaşıyor", "family", "İzmir", "Elif İzmir'de yaşıyor.", "Elif"),
         [("location", "İzmir", "Elif")]),
        # Not family at all: kept as a note, not as family (real: f07, f20).
        ("İş arkadaşım Deniz yeni bir eve taşındı.",
         proposal("Deniz yeni bir eve taşındı", "family", "yeni bir eve taşındı", "Deniz yeni bir eve taşındı.",
                  "Deniz"), [("note", "yeni bir eve taşındı", "Deniz")]),
        # ... but not in the model's words (Phase 8 bootstrap p04): held back.
        ("Arif'in kızı Ece üniversitede okuyor.",
         proposal("Arif'in kızı Ece üniversitede okuyor", "family", "üniversite öğrencisi",
                  "Ece üniversite öğrencisi.", "Ece", "Arif'in kızı"), []),
        # A named relative's job given as family (Phase 9.1 run 1, b13 / b17).
        ("Kuzenim Can Ankara'da avukat.", proposal("Can Ankara'da avukat", "family", "avukat", "Can Ankara'da avukat.",
                                                   "Can", "kuzeni"), [("occupation", "avukat", "Can")]),
        ("Eşim Zeynep hemşire.", proposal("Eşim Zeynep hemşire", "family", "hemşire", "Kullanıcının eşi Zeynep hemşire.",
                                          "Zeynep", "eşi"), [("occupation", "hemşire", "Zeynep")]),
        ("Komşum Ahmet doktor.", proposal("Ahmet doktor", "note", "doktor", "Ahmet doktor.", "Ahmet", "komşusu"),
         [("occupation", "doktor", "Ahmet")]),
        ("Ahmet'e kitap aldım.", proposal("Ahmet'e kitap aldım", "note", "kitap aldı", "Kullanıcı Ahmet'e kitap aldı.",
                                          "Ahmet"), [("note", "kitap aldı", "Ahmet")]),
        # Family stays family, and its value says whose (real: family "öğretmen").
        ("Annem öğretmen.", proposal("Annem öğretmen.", "family", "öğretmen", "Kullanıcının annesi öğretmen."),
         [("family", "annesi öğretmen", "user")]),
        ("Ece'nin iki çocuğu var.", proposal("Ece'nin iki çocuğu var", "family", "iki çocuğu var",
                                             "Ece'nin iki çocuğu var.", "Ece"), [("family", "iki çocuğu var", "Ece")]),
        # A workplace is not a city (real: f06 location "Atlas"): held back, not guessed.
        ("Atlas'ta çalışıyorum.", proposal("Atlas'ta çalışıyorum", "location", "Atlas", "Kullanıcı Atlas'ta çalışıyor."),
         []),
        ("İzmir'de çalışıyorum.", proposal("İzmir'de çalışıyorum", "location", "İzmir", "Kullanıcı İzmir'de çalışıyor."),
         []),
        ("İzmir'de yaşıyorum ve orada çalışıyorum.",
         proposal("İzmir'de yaşıyorum", "location", "İzmir", "Kullanıcı İzmir'de yaşıyor."), [("location", "İzmir", "user")]),
        # The user's own workplace, said with "çalıştığımı" (was a note).
        ("Atlas şirketinde çalıştığımı hafızana kaydet.",
         proposal("Atlas şirketinde çalıştığımı", "employer", "Atlas", "Kullanıcı Atlas şirketinde çalışıyor."),
         [("employer", "Atlas", "user")]),
        # A visit is not where one lives (real: Atlas — location "restoran"): held back.
        ("Dün Atlas adlı restorana gittim.",
         proposal("Dün Atlas adlı restorana gittim.", "location", "restoran", "Kullanıcı dün Atlas adlı restorana gitti.",
                  "Atlas"), []),
        ("Geçen yaz İzmir'e gittim.", proposal("Geçen yaz İzmir'e gittim", "location", "İzmir", "Kullanıcı İzmir'e gitti."), []),
        # Untouched: the right field already.
        ("İstanbul'da yaşıyorum.", proposal("İstanbul'da yaşıyorum.", "location", "İstanbul", "Kullanıcı İstanbul'da yaşıyor."),
         [("location", "İstanbul", "user")]),
        ("İzmir'e taşındım.", proposal("İzmir'e taşındım", "location", "İzmir", "Kullanıcı İzmir'e taşındı."),
         [("location", "İzmir", "user")]),
        # Being at a place is not living there (real, Phase 9 learning regression t08: the
        # model's statement says nothing of living either).
        ("Kervan'dan ayrıldım, artık Atlas'tayım.",
         proposal("artık Atlas'tayım", "location", "Atlas", "Kullanıcı artık Atlas'ta."), []),
        # Without work in the message it stays a city (Phase 9 guards regression f05).
        ("Bilgimi güncelle: artık İzmir'deyim.",
         proposal("artık İzmir'deyim", "location", "İzmir", "Kullanıcı artık İzmir'de."),
         [("location", "İzmir", "user")]),
        ("Artık İzmir'deyim, oraya taşındım.",
         proposal("Artık İzmir'deyim, oraya taşındım", "location", "İzmir", "Kullanıcı İzmir'e taşındı."),
         [("location", "İzmir", "user")]),
        ("Yazılım geliştiricisiyim.", proposal("Yazılım geliştiricisiyim.", "occupation", "yazılım geliştiricisi",
                                               "Kullanıcı yazılım geliştiricisi."),
         [("occupation", "yazılım geliştiricisi", "user")]),
        ("En sevdiğim renk yeşil.", proposal("En sevdiğim renk yeşil", "likes", "yeşil", "Kullanıcının sevdiği renk yeşil."),
         [("likes", "yeşil", "user")]),
        ("Hafızana kaydet: annemin doğum günü 9 Nisan.",
         proposal("annemin doğum günü 9 Nisan", "family", "9 Nisan", "Kullanıcının annesinin doğum günü 9 Nisan."),
         [("family", "annesinin doğum günü 9 Nisan", "user")]),
        ("Eskiden Kervan'da çalışıyordum.", proposal("Eskiden Kervan'da çalışıyordum", "employer", "Kervan",
                                                     "Kullanıcı eskiden Kervan'da çalışıyordu."),
         [("employer", "Kervan", "user")]),
        ("34 yaşında evlendim.", proposal("34 yaşında evlendim", "event", "34 yaşında evlendi", "Kullanıcı 34 yaşında evlendi."),
         [("event", "34 yaşında evlendi", "user")]),
    ],
)  # fmt: skip
def test_the_field_fits_the_meaning(
    message: str, item: dict[str, Any], expected: list[tuple[str, str, str]]
) -> None:
    assert written(message, item) == expected


def test_age_is_one_current_value() -> None:
    from lazis.memory import registry

    p = registry.get("age")
    assert p is not None and p.cardinality == "single" and p.kind == "profile"
    assert "age" in extraction.NOT_IN_PROMPT  # set from the words, never offered to the model


def test_the_extraction_prompt_is_unchanged_by_the_age_field() -> None:
    # The learning instruction is the cached prefix's neighbour: no new predicate in it.
    import re

    assert not re.search(r"\bage\b", extraction.predicates_for_prompt())
    enum = extraction.schema()["properties"]["items"]["items"]["properties"]["predicate"]["enum"]
    assert "age" not in enum


def test_a_correction_keeps_being_at_for_its_own_field() -> None:
    # "Kervan bilgisini düzelt: Atlas'tayım." — the request puts it in the field it corrects.
    item = proposal("Atlas'tayım", "location", "Atlas", "Kullanıcı Atlas'ta.")
    target = Target("m1", "msg", "Kervan bilgisini düzelt: Atlas'tayım.")
    assert extraction.validate([item], [target], request=True).accepted
    # Learning never reads a request's sentence; with leaving a job said, it holds it back.
    left = Target("m1", "msg", "Kervan'dan ayrıldım, artık Atlas'tayım.")
    assert not extraction.validate([item], [left]).accepted
