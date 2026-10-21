"""Namesakes stated in one message (Phase 7.2): what the user's words say, before any model
output is trusted — counted names with their slots, and one person with several roles."""

from __future__ import annotations

import pytest

from lazis.memory.namesakes import stated

# (message, [(name, count, [slot relationship type or slot words])], same-person name keys)
GROUPS: list[tuple[str, list[tuple[str, int, list[str]]], set[str]]] = [
    # the brief's sentences
    ("İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım.",
     [("Ahmet", 2, ["neighbor", "colleague"])], set()),
    ("İki Ahmet tanıyorum. Biri komşum, diğeri iş arkadaşım.",
     [("Ahmet", 2, ["neighbor", "colleague"])], set()),
    ("İki Mehmet tanıyorum, biri öğretmen, diğeri mühendis.",
     [("Mehmet", 2, ["ogretmen", "muhendis"])], set()),
    ("Üç Ayşe var hayatımda: kuzenim, komşum ve iş arkadaşım.",
     [("Ayşe", 3, ["cousin", "neighbor", "colleague"])], set()),
    ("İki Murat var; biri eski iş arkadaşım, diğeri çocukluk arkadaşım.",
     [("Murat", 2, ["colleague", "childhood_friend"])], set()),
    ("Ahmet ve Mehmet benim iş arkadaşlarım.", [], set()),
    ("Ahmet'in iki kardeşi var: Mehmet ve Ali.", [], set()),
    ("Ahmet hem komşum hem iş arkadaşım.", [], {"ahmet"}),
    # names repeated in the slots
    ("İki Ahmet tanıyorum: biri komşum Ahmet, diğeri iş arkadaşım Ahmet.",
     [("Ahmet", 2, ["neighbor", "colleague"])], set()),
    ("İki Zeynep var, biri kuzenim Zeynep, öbürü komşum Zeynep.",
     [("Zeynep", 2, ["cousin", "neighbor"])], set()),
    # "adında", "isminde", "tane", "farklı", "ayrı"
    ("Ahmet adında iki arkadaşım var: biri komşum, diğeri kuzenim.",
     [("Ahmet", 2, ["neighbor", "cousin"])], set()),
    ("Elif isminde iki tanıdığım var: biri kuzenim, diğeri iş arkadaşım.",
     [("Elif", 2, ["cousin", "colleague"])], set()),
    ("İki tane Zeynep var, biri kuzenim diğeri komşum.",
     [("Zeynep", 2, ["cousin", "neighbor"])], set()),
    ("İki farklı Can tanıyorum: biri komşum, diğeri iş arkadaşım.",
     [("Can", 2, ["neighbor", "colleague"])], set()),
    ("İki ayrı Deniz var: biri kuzenim, diğeri arkadaşım.",
     [("Deniz", 2, ["cousin", "friend"])], set()),
    ("2 Burak var: biri komşum, diğeri kuzenim.", [("Burak", 2, ["neighbor", "cousin"])], set()),
    ("3 Selin tanıyorum: kuzenim, komşum ve arkadaşım.",
     [("Selin", 3, ["cousin", "neighbor", "friend"])], set()),
    # four, and ordinals
    ("Dört Mehmet var: biri kuzenim, biri komşum, biri iş arkadaşım, biri çocukluk arkadaşım.",
     [("Mehmet", 4, ["cousin", "neighbor", "colleague", "childhood_friend"])], set()),
    ("Üç Ali var: ilki kuzenim; ikincisi komşum; üçüncüsü iş arkadaşım.",
     [("Ali", 3, ["cousin", "neighbor", "colleague"])], set()),
    # occupations and other words as slots
    ("İki Ece var: biri doktor, diğeri avukat.", [("Ece", 2, ["doktor", "avukat"])], set()),
    ("İki Kemal tanıyorum, biri Ankara'da, diğeri İzmir'de yaşıyor.",
     [("Kemal", 2, ["ankara", "izmir yasiyor"])], set()),
    ("İki Hakan var: biri mimar, diğeri komşum.", [("Hakan", 2, ["mimar", "neighbor"])], set()),
    # modifiers and labels
    ("İki Can var: biri eski müdürüm, diğeri komşum.", [("Can", 2, ["manager", "neighbor"])], set()),
    ("Ahmet adında iki arkadaşım var: biri üniversiteden arkadaşım, diğeri eski patronum.",
     [("Ahmet", 2, ["friend", "employer"])], set()),
    ("İki Sinan var: biri en yakın arkadaşım, diğeri iş arkadaşım.",
     [("Sinan", 2, ["friend", "colleague"])], set()),
    # surnames, Turkish letters, nicknames
    ("İki Ahmet Yılmaz tanıyorum: biri komşum, diğeri eski patronum.",
     [("Ahmet Yılmaz", 2, ["neighbor", "employer"])], set()),
    ("İki Ali Rıza var, biri kuzenim diğeri komşum.", [("Ali Rıza", 2, ["cousin", "neighbor"])], set()),
    ("İki Çağla var: biri kuzenim, diğeri komşum.", [("Çağla", 2, ["cousin", "neighbor"])], set()),
    ("İki Şükrü tanıyorum: biri amcam, diğeri komşum.", [("Şükrü", 2, ["uncle_paternal", "neighbor"])], set()),
    ("İki Ömer var: biri iş arkadaşım, diğeri arkadaşım.", [("Ömer", 2, ["colleague", "friend"])], set()),
    ("İki Ümit var: biri kuzenim, diğeri komşum.", [("Ümit", 2, ["cousin", "neighbor"])], set()),
    ("İki Gülşen var: biri teyzem, diğeri komşum.", [("Gülşen", 2, ["aunt_maternal", "neighbor"])], set()),
    ("İki İlker tanıyorum: biri kuzenim, diğeri iş arkadaşım.",
     [("İlker", 2, ["cousin", "colleague"])], set()),
    ("İki Memo var: biri kuzenim, diğeri komşum.", [("Memo", 2, ["cousin", "neighbor"])], set()),
    # the same relationship for both — two people still
    ("İki Ahmet var, ikisi de iş arkadaşım.", [("Ahmet", 2, [])], set()),
    ("İki Mehmet tanıyorum: biri iş arkadaşım, diğeri de iş arkadaşım.",
     [("Mehmet", 2, ["colleague", "colleague"])], set()),
    # counted without slots: the count is still known
    ("İki Ahmet tanıyorum.", [("Ahmet", 2, [])], set()),
    ("İki Ahmet tanıyorum. Yarın ikisi de gelecek.", [("Ahmet", 2, [])], set()),
    ("İki Ahmet var: biri komşum.", [("Ahmet", 2, [])], set()),  # one slot for two people
    # not namesakes
    ("Hem Ahmet hem Mehmet geldi.", [], set()),
    ("İki gün önce Ahmet geldi.", [], set()),
    ("İki kişi aradı, biri Ahmet'ti.", [], set()),
    ("İki arkadaşım var, Sena ile Barış.", [], set()),
    ("Ahmet ile Mehmet aynı okulda okudu.", [], set()),
    ("Bugün iki toplantım var.", [], set()),
    ("İki çocuğum var: Ege ve Defne.", [], set()),
    ("Mehmet iki yıl önce taşındı.", [], set()),
    ("Ahmet'in iki kızı var.", [], set()),
    ("İki Ahmet'in de doğum günü mayısta.", [("Ahmet", 2, [])], set()),
    # one person, several roles
    ("Zeynep hem kuzenim hem de en yakın arkadaşım.", [], {"zeynep"}),
    ("Ahmet komşum, aynı zamanda iş arkadaşım.", [], {"ahmet"}),
    ("Kerem hem öğretmen hem yazar.", [], {"kerem"}),
    ("Hem Ahmet hem de Mehmet komşum.", [], set()),
    # two groups in one message
    ("İki Ahmet var: biri komşum, diğeri kuzenim. İki Ayşe de var: biri teyzem, diğeri arkadaşım.",
     [("Ahmet", 2, ["neighbor", "cousin"]), ("Ayşe", 2, ["aunt_maternal", "friend"])], set()),
]  # fmt: skip


@pytest.mark.parametrize(("message", "groups", "same"), GROUPS)
def test_what_the_user_says(
    message: str, groups: list[tuple[str, int, list[str]]], same: set[str]
) -> None:
    st = stated(message)
    got = [(g.name, g.count, [s.type or s.words for s in g.slots]) for g in st.groups]
    assert got == groups
    assert set(st.same) == same


# Generated: every slot pair of the common relationships, with Turkish names.
_REL_WORDS = {
    "komşum": "neighbor", "iş arkadaşım": "colleague", "kuzenim": "cousin",
    "çocukluk arkadaşım": "childhood_friend", "arkadaşım": "friend",
}  # fmt: skip
_NAMES = ["Ahmet", "Ayşe", "Gökhan", "Şeyma", "Özgür", "İpek"]
GENERATED = [(name, a, b) for name in _NAMES for a in _REL_WORDS for b in _REL_WORDS if a < b][:48]


@pytest.mark.parametrize(("name", "first", "second"), GENERATED)
def test_two_namesakes_with_any_two_relationships(name: str, first: str, second: str) -> None:
    st = stated(f"İki {name} tanıyorum: biri {first}, diğeri {second}.")
    assert [(g.name, g.count) for g in st.groups] == [(name, 2)]
    assert [s.type for s in st.groups[0].slots] == [_REL_WORDS[first], _REL_WORDS[second]]


def test_slot_labels_keep_the_users_words() -> None:
    st = stated(
        "Ahmet adında iki arkadaşım var: biri üniversiteden arkadaşım, diğeri eski patronum."
    )
    assert [s.label for s in st.groups[0].slots] == ["üniversiteden arkadaşı", "eski işvereni"]
    st = stated("İki Murat var; biri eski iş arkadaşım, diğeri çocukluk arkadaşım.")
    assert [s.label for s in st.groups[0].slots] == ["eski iş arkadaşı", "çocukluk arkadaşı"]
    st = stated("İki Ece var: biri doktor, diğeri avukat.")
    assert [(s.label, s.surface) for s in st.groups[0].slots] == [
        (None, "doktor"),
        (None, "avukat"),
    ]
