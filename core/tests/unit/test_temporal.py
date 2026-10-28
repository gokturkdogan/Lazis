"""When the user's words say something is true (Phase 9, test group B, part 1): 70 sentences —
past, current, future; changes; clauses; the time the user named (never a computed date).
Pure, synthetic data only."""

from __future__ import annotations

import pytest

from lazis.memory import refine, temporal

# (sentence, quote (None = the whole sentence), anchor, expected tense)
TENSES: list[tuple[str, str | None, str | None, str]] = [
    # past: adverbs, past continuous, past forms of living / working somewhere
    ("Eskiden öğretmendim.", None, None, "past"),
    ("Önceden Ankara'da yaşıyordum.", None, None, "past"),
    ("Bir zamanlar Bursa'da otururduk.", None, None, "past"),
    ("Geçen yıl Kervan Lojistik'te çalışıyordum.", None, None, "past"),
    ("Çocukken Rize'de yaşardık.", None, None, "past"),
    ("Öğrenciyken garsonluk yapıyordum.", None, None, "past"),
    ("İstanbul, Ankara ve İzmir'de yaşadım.", None, None, "past"),
    ("Üç yıl Konya'da çalıştım.", None, None, "past"),
    ("Ankara'da okudum.", None, None, "past"),
    ("Mehmet eskiden muhasebeciydi.", None, None, "past"),
    ("Ahmet eskiden İzmir'de yaşıyordu.", None, None, "past"),
    ("Eskiden kahve içmezdim.", None, None, "past"),
    ("Vaktiyle Almanya'da kaldım.", None, None, "past"),
    ("Beş yıl önce Eskişehir'de oturuyordum.", None, None, "past"),
    ("Taşınmadan önce Kadıköy'e taşınmıştım.", None, None, "past"),
    # current: present, "artık", "şimdi", a change that happened
    ("Artık yazılım geliştiricisiyim.", None, None, "current"),
    ("Şimdi İstanbul'dayım.", None, None, "current"),
    ("Kervan'da çalışıyorum.", None, None, "current"),
    ("İzmir'de yaşıyorum.", None, None, "current"),
    ("Ahmet öğretmen.", None, None, "current"),
    ("Mehmet 2024'te İzmir'e taşındı.", None, None, "current"),
    ("LAZIS projesini geçen ay başlattım.", None, None, "current"),
    ("Pusula Yazılım'a geçtim.", None, None, "current"),
    ("Geçen hafta yeni işe başladım.", None, None, "current"),
    ("Geçen yıl evlendim.", None, None, "current"),
    ("Artık sigara içmiyorum.", None, None, "current"),
    ("Yemek yapmayı severim.", None, None, "current"),
    ("Adım Kerem.", None, None, "current"),
    ("Her sabah koşarım.", None, None, "current"),
    ("Sıcaktan hiç hoşlanmam.", None, None, "current"),
    ("2023'ten beri Pusula'da çalışıyorum.", None, None, "current"),
    ("Kız kardeşim Elif pilot.", None, None, "current"),
    ("Ahmet bana öğretmen olduğunu söyledi.", None, None, "current"),
    ("İki projem var: LAZIS ve LINEUP.", None, None, "current"),
    ("Kendi şirketimi kurdum.", None, None, "current"),
    # future: -acak/-ecek, next year, plans
    ("Gelecek yıl İzmir'e taşınacağım.", None, None, "future"),
    ("Seneye emekli olacak.", None, None, "future"),
    ("Yakında yeni bir işe başlayacağım.", None, None, "future"),
    ("Haftaya Ankara'ya gideceğim.", None, None, "future"),
    ("Mehmet gelecek ay evlenecek.", None, None, "future"),
    ("İleride kendi şirketimi kurmayı planlıyorum.", None, None, "future"),
    ("Önümüzdeki yaz Berlin'e taşınacağız.", None, None, "future"),
    ("Japonca öğreneceğim.", None, None, "future"),
    # two clauses: the quote / the anchor picks one
    ("Eskiden öğretmendim, artık yazılım geliştiricisiyim.", "Eskiden öğretmendim", None, "past"),
    ("Eskiden öğretmendim, artık yazılım geliştiricisiyim.", "artık yazılım geliştiricisiyim",
     None, "current"),
    ("Önceden Ankara'da yaşıyordum, şimdi İstanbul'dayım.", "Ankara'da yaşıyordum", None, "past"),
    ("Önceden Ankara'da yaşıyordum, şimdi İstanbul'dayım.", "şimdi İstanbul'dayım", None,
     "current"),
    ("Geçen yıl Kervan Lojistik'te çalışıyordum, artık Pusula Yazılım'dayım.", None,
     "Kervan Lojistik", "past"),
    ("Geçen yıl Kervan Lojistik'te çalışıyordum, artık Pusula Yazılım'dayım.", None,
     "Pusula Yazılım", "current"),
    ("Eskiden kahve içmezdim, şimdi her sabah içiyorum.", "şimdi her sabah içiyorum", None,
     "current"),
    ("Ankara'da yaşıyordum ama artık İzmir'deyim.", None, "İzmir", "current"),
    ("Ankara'da yaşıyordum ama artık İzmir'deyim.", None, "Ankara", "past"),
    ("Bursa'da oturuyorum, seneye Antalya'ya taşınacağım.", None, "Antalya", "future"),
    ("Bursa'da oturuyorum, seneye Antalya'ya taşınacağım.", None, "Bursa", "current"),
]  # fmt: skip


@pytest.mark.parametrize(("sentence", "quote", "anchor", "want"), TENSES)
def test_tense(sentence: str, quote: str | None, anchor: str | None, want: str) -> None:
    assert temporal.tense_of(sentence, quote or sentence, anchor) == want


@pytest.mark.parametrize(
    ("sentence", "marked"),
    [
        ("Mehmet İstanbul'da yaşıyor.", False),
        ("Mehmet artık İzmir'de yaşıyor.", True),
        ("Mehmet İzmir'e taşındı.", True),
        ("2023'ten beri Pusula'da çalışıyorum.", True),
        ("Ahmet mimar.", False),
        ("Kervan'dan ayrıldım.", True),
        ("Sigarayı bıraktım.", True),
        ("Aslında Ankara'da yaşıyor.", True),
        ("Yanlış söyledim, Bursa'da yaşıyor.", True),
        ("Ahmet yeni bir işe girdi.", True),
        ("Telefonum Pixel 8.", False),
        ("İzmir'de oturuyor.", False),
    ],
)
def test_change_marked(sentence: str, marked: bool) -> None:
    assert temporal.change_marked(sentence) is marked


@pytest.mark.parametrize(
    ("clause", "phrase"),
    [
        ("Mehmet 2024'te İzmir'e taşındı", "2024'te"),
        ("LAZIS projesini geçen ay başlattım", "geçen ay"),
        ("Geçen yıl Kervan'da çalışıyordum", "Geçen yıl"),
        ("Gelecek yıl İzmir'e taşınacağım", "Gelecek yıl"),
        ("Mart 2025'te evlendik", "Mart 2025"),
        ("2023'ten beri Pusula'da çalışıyorum", "2023'ten beri"),
        ("Üç yıl önce Konya'dan geldim", "Üç yıl önce"),
        ("Çocukken Rize'de yaşardık", "Çocukken"),
        ("Ahmet mimar", None),
        ("Her sabah koşarım", None),
    ],
)
def test_time_phrase_is_the_users_words_never_a_date(clause: str, phrase: str | None) -> None:
    got = temporal.time_phrase(clause)
    assert (got.casefold() if got else None) == (phrase.casefold() if phrase else None)


def test_a_comma_inside_a_list_does_not_end_a_clause() -> None:
    assert temporal.clauses("İstanbul, Ankara ve İzmir'de yaşadım.") == [
        "İstanbul, Ankara ve İzmir'de yaşadım"
    ]
    assert temporal.clauses("Eskiden öğretmendim, artık yazılım geliştiricisiyim.") == [
        "Eskiden öğretmendim",
        "artık yazılım geliştiricisiyim",
    ]


@pytest.mark.parametrize(
    ("clause", "anchor", "want"),
    [
        ("Kervan'dan ayrıldım", "Kervan", True),
        ("Pusula'dan istifa ettim", "Pusula", True),
        ("Ankara'dan ayrıldık", "Ankara", True),
        ("Kervan'dan ayrıldım", "Atlas", False),  # not in the clause
        ("Ankara'dan ayrılıp İzmir'e taşındım", "İzmir", False),  # arrived somewhere
        ("Kervan'dan ayrıldım, artık Atlas'tayım", "Atlas", False),
        ("Sigarayı bıraktım", "sigarayı bıraktı", False),  # the value is the leaving itself
        ("Kervan'da çalışıyorum", "Kervan", False),
    ],
)
def test_what_the_user_left_is_in_the_past(clause: str, anchor: str, want: bool) -> None:
    assert temporal.left(clause, anchor) is want


@pytest.mark.parametrize(
    ("clause", "key", "over"),
    [
        ("Kız kardeşim Elif eskiden İzmir'de yaşıyordu", "sibling", False),
        ("Kardeşim Elif eskiden öğretmendi", "sibling", False),
        ("Eskiden komşum Ahmet Ankara'da yaşıyordu", "neighbor", False),
        ("Arkadaşım Burak geçen yıl Bursa'daydı", "friend", False),
        ("Ahmet eskiden komşumdu", "neighbor", True),
        ("Eski komşum Ahmet Ankara'da yaşıyordu", "neighbor", True),
        ("Eskiden Burak'la arkadaştık", "friend", True),
        ("Geçen yıl Can'la aynı ekipte çalışıyorduk", "colleague", True),
        ("Eskiden Kervan'da çalışıyordum", "works_at", True),  # a workplace is the verb itself
        ("Önceden Bursa'da yaşıyordum", "lives_in", True),
    ],
)  # fmt: skip
def test_a_past_clause_ends_a_relationship_between_people_only_when_it_says_so(
    clause: str, key: str, over: bool
) -> None:
    assert refine.relationship_over(clause, key) is over


@pytest.mark.parametrize(
    ("clause", "value", "denied"),
    [
        ("Artık Kervan Lojistik'te çalışmıyorum", "Kervan Lojistik", True),
        ("İstanbul'da artık yaşamıyorum", "İstanbul", True),
        ("Artık öğretmen değilim", "öğretmen", True),
        ("Artık öğretmenlik yapmıyorum", "öğretmen", True),
        ("Kervan'da değil Atlas'ta çalışıyorum", "Kervan", True),
        ("Kervan'da değil Atlas'ta çalışıyorum", "Atlas", False),
        ("Kervan Lojistik'te çalışıyorum ama mutlu değilim", "Kervan Lojistik", False),
        ("Atlas Yazılım'a geçtim", "Atlas Yazılım", False),
        ("Bursa'da yaşıyorum", "Bursa", False),
        ("Ankara'yı hiç sevmiyorum", "İzmir", False),
    ],
)
def test_a_value_is_denied_only_by_the_word_right_after_it(
    clause: str, value: str, denied: bool
) -> None:
    assert refine.said_with_not(clause, value) is denied
