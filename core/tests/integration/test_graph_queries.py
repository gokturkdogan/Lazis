"""Deterministic relationship queries (memory.graph): Turkish questions → typed queries →
bounded walks over stored relationships. Synthetic people only."""

from __future__ import annotations

import pytest

from lazis.memory import graph
from lazis.memory import repository as repo
from lazis.storage import StorageHandle
from tests.graph_support import World, run


def ask(storage: StorageHandle, question: str) -> graph.Answer | None:
    return run(storage, lambda c: graph.ask(c, question))


def answer(storage: StorageHandle, question: str) -> graph.Answer:
    a = ask(storage, question)
    assert a is not None, question
    return a


def names(storage: StorageHandle, a: graph.Answer) -> list[str]:
    return sorted(e.name for e in (run(storage, lambda c: [repo.get_entity(c, i) for i in a.results]))
                  if e is not None)  # fmt: skip


# ----- chains -------------------------------------------------------------------------------
def test_the_briefs_three_step_chain(storage: StorageHandle, world: World) -> None:
    a = answer(storage, "Çocukluk arkadaşımın kardeşinin eşi kim?")
    assert a.status == "unique" and a.results == (world["elif"],)
    assert a.lines[0] == "Soru: kullanıcının çocukluk arkadaşının kardeşinin eşi"
    assert "Cevap: Elif" in a.lines
    assert a.lines[-1] == (
        "Dayanak: Ahmet: kullanıcının çocukluk arkadaşı → Mehmet: Ahmet'in kardeşi"
        " → Elif: Mehmet'in eşi"
    )
    assert len(a.relationship_ids) == 3


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("çocukluk arkadaşımın kardeşi kim", ["Mehmet"]),
        ("Benim çocukluk arkadaşımın kardeşi kimdir?", ["Mehmet"]),
        ("Annemin kardeşi kim?", ["Fatma"]),
        ("annemin adı ne", ["Ayşe"]),
        ("Çocukluk arkadaşım Ahmet'in kardeşi kim?", ["Mehmet"]),
        ("İş ortağım Ahmet'in kardeşi kim?", []),
        ("Mehmet'in eşi kim?", ["Elif"]),
        ("Elif'in eşi kim?", ["Mehmet"]),  # symmetric, read from the other end
        ("Mehmet'in kardeşi kim?", ["Ahmet"]),
        ("Ayşe'nin çocuğu kim?", ["Kullanıcı"]),  # mother read from the target
        ("Mehmet nerede çalışıyor?", ["Kervan Lojistik"]),
        ("Mehmet hangi projede çalışıyor?", ["Pusula"]),
        ("Pusula projesinde kim çalışıyor?", ["Elif", "Mehmet"]),
        ("Kervan Lojistik'te kimler çalışıyor?", ["Mehmet"]),  # Zeynep's job ended
        ("Mehmet nerede yaşıyor?", ["İzmir"]),
        ("Mehmet'in çalıştığı yer neresi?", ["Kervan Lojistik"]),
        ("Mehmetin karısı kim", ["Elif"]),
        ("Elif'in kocası kim", ["Mehmet"]),
        ("Annemin kardeşinin adı neydi?", ["Fatma"]),
        ("cocukluk arkadasimin kardesi kim", ["Mehmet"]),
        ("Kardeşim kim?", []),
        ("Çocukluk arkadaşımın kardeşi nerede çalışıyor?", ["Kervan Lojistik"]),
        ("Ahmet'in kuzeni kim?", None),  # two Ahmets: ask
        ("Çocukluk arkadaşım Ahmet'in kuzeni kim?", ["Zeynep"]),
    ],
)
def test_chains(
    storage: StorageHandle, world: World, question: str, expected: list[str] | None
) -> None:
    a = answer(storage, question)
    if expected is None:
        assert a.status == "ambiguous" and a.unresolved == "Ahmet"
        assert {e.relation for e in a.options} == {"çocukluk arkadaşı", "iş ortağı"}
        return
    assert names(storage, a) == expected, a.lines
    assert a.status == ("unique" if len(expected) == 1 else "several" if expected else "none")


def test_no_inference_beyond_what_was_stated(storage: StorageHandle, world: World) -> None:
    # Mother's sister is the user's aunt in life — but it was never stated: no answer.
    a = answer(storage, "Teyzem kim?")
    assert a.status == "none" and "teyzesi kişisel hafızada kayıtlı değil" in a.lines[-1]
    # A friend's sibling is not the user's friend.
    assert answer(storage, "Arkadaşlarım kimler?").results == (world["ahmet"],)
    # A one-way relation is not read backwards: Ali knows Mehmet, Mehmet's acquaintance is unknown.
    assert answer(storage, "Mehmet'in tanıdığı kim?").status == "none"
    assert answer(storage, "Ali'nin tanıdığı kim?").results == (world["mehmet"],)
    # The generic "parent" never answers "mother": the gender was not stated.
    assert answer(storage, "Fatma'nın annesi kim?").status == "none"


def test_a_broken_chain_says_where_it_broke(storage: StorageHandle, world: World) -> None:
    a = answer(storage, "Çocukluk arkadaşımın kardeşinin annesi kim?")
    assert a.status == "none"
    assert a.lines[1] == "Bilinen: Ahmet: kullanıcının çocukluk arkadaşı → Mehmet: Ahmet'in kardeşi"
    assert "Mehmet'in annesi kişisel hafızada kayıtlı değil" in a.lines[2]


def test_ended_relationships_are_past_not_current(storage: StorageHandle, world: World) -> None:
    a = answer(storage, "Zeynep'in eşi kim?")
    assert a.status == "none"
    assert any(line.startswith("Geçmiş kayıt: Can: Zeynep'in eşi (geçmişte") for line in a.lines)


def test_yes_no_check(storage: StorageHandle, world: World) -> None:
    yes = answer(storage, "Ahmet'in kardeşi Mehmet mi?")
    assert yes.status == "ambiguous"  # two Ahmets, still asks
    yes = answer(storage, "Çocukluk arkadaşım Ahmet'in kardeşi Mehmet mi?")
    assert yes.lines[1] == "Cevap: evet — Mehmet."
    no = answer(storage, "Mehmet'in eşi Deniz mi?")
    assert no.lines[1].startswith("Cevap: hayır") and "Elif" in no.lines[1]


def test_cycles_are_not_answers(storage: StorageHandle, world: World) -> None:
    # Mehmet's sibling is Ahmet; Ahmet's sibling (other than Mehmet) is unknown.
    a = answer(storage, "Mehmet'in kardeşinin kardeşi kim?")
    assert a.status == "none"


def test_unknown_names(storage: StorageHandle, world: World) -> None:
    a = answer(storage, "Burak'ın kardeşi kim?")
    assert a.status == "unknown" and "«Burak»" in a.lines[0]


# ----- sensitive ----------------------------------------------------------------------------
def test_sensitive_relationships_only_when_asked(storage: StorageHandle, world: World) -> None:
    a = answer(storage, "Çocukluk arkadaşım Ahmet'in sevgilisi kim?")
    assert a.results == (world["selin"],)
    listing = answer(storage, "Zeynep'in kimlerle bağlantısı var?")
    assert "Selin" not in " ".join(listing.lines)
    paths = answer(storage, "Selin'i nereden tanıyorum?")
    assert paths.status == "none"  # the only path runs through the intimate relationship


# ----- paths and neighbours -----------------------------------------------------------------
def test_where_do_i_know_someone_from(storage: StorageHandle, world: World) -> None:
    a = answer(storage, "Zeynep'i nereden tanıyorum?")
    assert a.status == "unique"
    assert a.lines[1] == "- Ahmet: kullanıcının çocukluk arkadaşı → Zeynep: Ahmet'in kuzeni"
    elif_ = answer(storage, "Elif'i nereden tanıyorum?")
    assert elif_.lines[1] == (
        "- Ahmet: kullanıcının çocukluk arkadaşı → Mehmet: Ahmet'in kardeşi → Elif: Mehmet'in eşi"
    )


def test_pair_questions(storage: StorageHandle, world: World) -> None:
    married = answer(storage, "Elif ile Mehmet evli mi?")
    assert married.query.kind == "path" and married.lines[1] == "- Mehmet: Elif'in eşi"
    me = answer(storage, "Mehmet ile ben nasıl bağlantılıyız?")
    assert me.lines[1] == "- Ahmet: Mehmet'in kardeşi → Kullanıcı: Ahmet'in çocukluk arkadaşı"
    assert answer(storage, "Elif'le Ahmet arasında ne var?").status == "ambiguous"
    work = answer(storage, "Pusula'da kimler çalışıyor?")
    assert "- Elif — dayanak: Pusula: Elif'in çalıştığı proje" in work.lines


def test_what_is_someone_to_someone(storage: StorageHandle, world: World) -> None:
    a = answer(storage, "Elif, Mehmet'in neyi oluyor?")
    assert a.query.kind == "path" and a.lines[1] == "- Elif: Mehmet'in eşi"
    none = answer(storage, "Fatma, Elif'in nesi?")
    assert none.status == "none"


def test_paths_between_two_people(storage: StorageHandle, world: World) -> None:
    a = answer(storage, "Elif ile Zeynep arasında nasıl bir bağlantı var?")
    assert a.status == "unique"  # via Mehmet and Ahmet: 3 steps, within the bound
    assert a.lines[1].startswith("- Mehmet: Elif'in eşi → Ahmet: Mehmet'in kardeşi → Zeynep")
    far = answer(storage, "Fatma ile Zeynep arasında bir bağlantı var mı?")
    assert far.status == "none" and "en fazla 3 adım" in far.lines[0]


def test_paths_are_bounded_and_cycle_free(storage: StorageHandle, world: World) -> None:
    found = run(storage, lambda c: graph.paths_between(c, world["elif"], world["zeynep"]))
    for p in found:
        assert len(p.hops) <= graph.MAX_HOPS
        assert len(set(p.nodes)) == len(p.nodes)


def test_neighbours_and_family(storage: StorageHandle, world: World) -> None:
    a = answer(storage, "Mehmet'in kimlerle bağlantısı var?")
    text = "\n".join(a.lines)
    family = next(line for line in a.lines if line.startswith("Aile: "))
    assert sorted(family.removeprefix("Aile: ").split("; ")) == [
        "Ahmet: Mehmet'in kardeşi", "Deniz: Mehmet'in eski eşi", "Elif: Mehmet'in eşi"]  # fmt: skip
    assert "Kurum: Kervan Lojistik: Mehmet'in çalıştığı yer" in text
    assert "Ali: Mehmet'in tanıdığı" not in text and "Mehmet: Ali'nin tanıdığı" in text
    fam = answer(storage, "Ailem hakkında ne biliyorsun?")
    assert fam.lines[1] == "Aile: Ayşe: kullanıcının annesi"
    zeynep = answer(storage, "Zeynep'in kimlerle bağlantısı var?")
    assert any(line.startswith("Geçmişte:") and "Kervan" in line for line in zeynep.lines)


def test_who_is(storage: StorageHandle, world: World) -> None:
    a = answer(storage, "Elif kim?")
    assert "Elif: Mehmet'in eşi" in "\n".join(a.lines)
    assert a.lines[-1].startswith("Kullanıcıyla bağlantısı: Ahmet: kullanıcının çocukluk arkadaşı")


# ----- not questions ------------------------------------------------------------------------
@pytest.mark.parametrize(
    "said",
    [
        "Çocukluk arkadaşım Ahmet'in kardeşi Mehmet Ankara'ya taşındı.",
        "Ailemle tatile gittik.",
        "Mehmet'in eşi çok iyi yemek yapıyor.",
        "Bugün hava güzel.",
        "Python'da liste nasıl sıralanır?",
        "Kardeşim yarın geliyor.",
    ],
)
def test_statements_are_not_queries(storage: StorageHandle, world: World, said: str) -> None:
    assert ask(storage, said) is None


def test_forgotten_people_leave_no_trace(storage: StorageHandle, world: World) -> None:
    from lazis.memory import service

    run(storage, lambda c: service.forget_entity(c, world["mehmet"]))
    assert answer(storage, "Çocukluk arkadaşımın kardeşinin eşi kim?").status == "none"
    elif_ = answer(storage, "Elif'i nereden tanıyorum?")
    assert elif_.status == "none" and "Mehmet" not in " ".join(elif_.lines)
