"""Phase 10A: what the reply may not say about people — certainty about an unsettled
namesake, and things the user asked to forget (the synthetic graph: two Ahmets, the
childhood friend's sibling Mehmet and cousin Zeynep)."""

from __future__ import annotations

import pytest

from lazis.conversation import people
from lazis.ids import utc_now_iso
from lazis.memory import forgotten, relationships, service, text, unsettled
from lazis.memory import repository as repo
from lazis.memory.extraction import Candidate
from lazis.memory.service import Source
from lazis.storage import StorageHandle, driver
from lazis.storage.unit_of_work import UnitOfWork
from tests.graph_support import World, run

BOTH = ("ahmet", "ahmet2")


def fact(c: driver.Connection, subject_id: str | None, predicate: str, value: str) -> str:
    now = utc_now_iso()
    with UnitOfWork(c, kind="user_edit", actor="user", summary="seed") as uow:
        m = repo.insert_memory(
            c, kind="fact", subject_id=subject_id, predicate=predicate, value=value,
            content=value, keywords="", status="active", origin="stated", confidence=0.9,
            importance=0.5, sensitivity="normal", sensitivity_category=None, event_time=None,
            valid_from=None, supersedes_id=None, change_set_id=uow.change_set_id, now=now,
        )  # fmt: skip
        repo.add_evidence(c, m.id, source_type="user_edit", source_ref=None, quote=None, now=now)
    return m.id


def group(
    storage: StorageHandle, world: World, keys: tuple[str, ...] = BOTH
) -> unsettled.Unsettled:
    found = run(storage, lambda c: unsettled.load(c, [world[k] for k in keys]))
    assert len(found) == 1
    return found[0]


def guarded(reply: str, ctx: people.Context, chunk: int = 0) -> tuple[str, dict[str, int]]:
    g = people.PeopleGuard(ctx=ctx)
    if chunk:
        out = "".join(g.feed(reply[i : i + chunk]) for i in range(0, len(reply), chunk))
    else:
        out = g.feed(reply)
    out += g.finish()
    assert out == g.released
    return out, g.removed


# ----- who is unsettled ---------------------------------------------------------------------
def test_two_namesakes_with_their_labels_and_links(storage: StorageHandle, world: World) -> None:
    u = group(storage, world)
    assert u.name == "Ahmet" and not u.others_unknown
    friend, partner = u.candidates
    assert "childhood_friend" in friend.label_types and "business_partner" in partner.label_types
    assert (text.name_key("Mehmet"), "sibling") in friend.links
    assert (text.name_key("Zeynep"), "cousin") in friend.links


def test_a_name_the_message_settled_is_not_unsettled(storage: StorageHandle, world: World) -> None:
    # Recall holds back the other Ahmet's facts only: the message picked the friend.
    assert run(storage, lambda c: unsettled.load(c, [world["ahmet2"]])) == ()


# ----- certainty ----------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("sentence", "message", "kind"),
    [
        # Phase 7 sessions 3.ask: the stored one's sibling, said as the answer.
        ("Ahmet'in kardeşi Mehmet'tir.", "Ahmet'in kardeşi kim?", "fact"),
        ("Ahmet'in kuzeni Zeynep.", "Ahmet'in akrabaları kim?", "fact"),
        # Phase 9.1 namesakes a2: what the user said, attached to one of them.
        ("Çocukluk arkadaşınız olan Ahmet Bey'in emekli olduğunu anladım.",
         "Ahmet emekli oldu.", "label"),
        ("İş ortağınız Ahmet'ten bahsediyorsunuz.", "Ahmet bugün aradı.", "label"),
        ("Kastettiğiniz kişi iş ortağınız Ahmet.", "Ahmet bugün aradı.", "label"),
        # Not certainty: said with the label, asked, conditional, everyone listed, the user's own
        # words, or no name.
        ("Çocukluk arkadaşınız Ahmet'in kardeşi Mehmet.", "Ahmet'in kardeşi kim?", None),
        ("Hangi Ahmet'ten söz ediyorsunuz: çocukluk arkadaşınız mı, iş ortağınız mı?",
         "Ahmet'in kardeşi kim?", None),
        ("Çocukluk arkadaşınız Ahmet'i kastediyorsanız, kardeşi Mehmet.",
         "Ahmet'in kardeşi kim?", None),
        ("Çocukluk arkadaşınız Ahmet de iş ortağınız Ahmet de kayıtlı.", "Ahmet emekli oldu.",
         None),
        ("Ahmet Bey'in emekli olması güzel bir haber.", "Ahmet emekli oldu.", None),
        ("Ahmet'in kardeşi Mehmet'i de selamlayın.", "Ahmet ile kardeşi Mehmet geldi.", None),
        ("Kardeşi Mehmet'tir.", "Ahmet'in kardeşi kim?", None),
    ],
)  # fmt: skip
def test_certain_about_an_unsettled_person(
    storage: StorageHandle, world: World, sentence: str, message: str, kind: str | None
) -> None:
    assert unsettled.certain(sentence, group(storage, world), message) == kind


def test_a_stored_value_without_the_label(storage: StorageHandle, world: World) -> None:
    run(storage, lambda c: fact(c, world["ahmet2"], "occupation", "avukat"))
    u = group(storage, world)
    assert unsettled.certain("Ahmet avukat olarak çalışıyor.", u, "Ahmet ne iş yapıyor?") == "fact"
    assert unsettled.certain("İş ortağınız Ahmet avukat.", u, "Ahmet ne iş yapıyor?") is None
    assert unsettled.certain("Ahmet avukat, değil mi?", u, "Ahmet ne iş yapıyor?") is None
    assert unsettled.certain("Ahmet avukat olmuş.", u, "Ahmet avukat oldu.") is None


def test_one_stored_and_an_open_question(storage: StorageHandle, world: World) -> None:
    # Only the childhood friend is stored as unsettled with "başka biri mi?" pending: the
    # friend's label with the user's news decides who it is.
    run(storage, lambda c: repo.delete_entity(c, world["ahmet2"]))
    u = group(storage, world, ("ahmet",))
    assert u.others_unknown
    said = "Ahmet bugün aradı, satranç kulübüne yazılmış."
    assert (
        unsettled.certain("Çocukluk arkadaşınız Ahmet satranç kulübüne yazılmış.", u, said)
        == "label"
    )
    assert unsettled.certain("Ahmet'in satranç kulübüne yazılması güzel.", u, said) is None


# ----- the guard ----------------------------------------------------------------------------
@pytest.mark.parametrize("chunk", [0, 1, 2, 3, 7, 64])
def test_the_answer_is_dropped_and_the_question_kept(
    storage: StorageHandle, world: World, chunk: int
) -> None:
    message = "Ahmet'in kardeşi kim?"
    ctx = people.Context(message, (group(storage, world),))
    reply = ("Ahmet'in kardeşi Mehmet'tir. Ancak sistemde iki Ahmet var; çocukluk arkadaşınız "
             "olan mı, iş ortağınız olan mı?")  # fmt: skip
    out, removed = guarded(reply, ctx, chunk)
    assert out == "Sistemde iki Ahmet var; çocukluk arkadaşınız olan mı, iş ortağınız olan mı?"
    assert removed == {"unsettled_fact": 1}


@pytest.mark.parametrize("chunk", [0, 1, 4])
def test_a_reply_left_without_a_question_asks(
    storage: StorageHandle, world: World, chunk: int
) -> None:
    ctx = people.Context("Ahmet emekli oldu.", (group(storage, world),))
    reply = "Çocukluk arkadaşınız olan Ahmet Bey'in emekli olduğunu anladım. Hayırlı olsun efendim."
    out, removed = guarded(reply, ctx, chunk)
    assert out == "Hayırlı olsun efendim. Hangi Ahmet olduğunu belirtir misiniz?"
    assert removed == {"unsettled_label": 1}
    out, _ = guarded("Ahmet'in kardeşi Mehmet'tir.", people.Context("Ahmet'in kardeşi kim?",
                                                                     (group(storage, world),)))  # fmt: skip
    assert out == "Hangi Ahmet olduğunu belirtir misiniz?"


def test_nothing_to_check_passes_untouched(storage: StorageHandle, world: World) -> None:
    reply = "Ahmet'in kardeşi Mehmet'tir."
    g = people.PeopleGuard()
    assert g.feed(reply[:5]) == reply[:5]  # no holding at all
    assert g.feed(reply[5:]) + g.finish() == reply[5:]


def test_a_settled_message_keeps_the_answer(storage: StorageHandle, world: World) -> None:
    message = "Çocukluk arkadaşım Ahmet'in kardeşi kim?"
    ctx = run(storage, lambda c: people.build(c, (world["ahmet2"],), message, asking=True))
    assert ctx.unsettled == () and not ctx.active
    assert guarded("Ahmet'in kardeşi Mehmet'tir.", ctx)[0] == "Ahmet'in kardeşi Mehmet'tir."


# ----- forgotten ----------------------------------------------------------------------------
def index(storage: StorageHandle, message: str = "") -> forgotten.Index:
    return run(storage, lambda c: forgotten.load(c, message=message))


def test_nothing_forgotten_is_an_empty_index(storage: StorageHandle, world: World) -> None:
    assert index(storage).empty
    assert index(storage).speaks_of("Ahmet'in kardeşi Mehmet.") is None


def test_a_forgotten_pair(storage: StorageHandle, world: World) -> None:
    run(storage, lambda c: relationships.forget_pair(c, world["ahmet"], world["mehmet"]))
    idx = index(storage, "Mehmet, Ahmet'in neyi oluyor?")
    # Phase 7 sessions 6.ask: only Mehmet in the sentence, Ahmet in the user's message.
    assert idx.speaks_of("Mehmet bu kişilerden hangisinin kuzeniydi?") == "relationship"
    assert idx.speaks_of("Mehmet, Ahmet'in kardeşi.") == "relationship"
    assert idx.speaks_of("Ahmet ile Mehmet arasında yakın bir ilişki var.") == "relationship"
    # Saying there is no record of it says nothing of it (Phase 10A real run, f1).
    assert idx.speaks_of("Mehmet ile Ahmet arasında kayıtlı bir ilişki bulunmuyor.") is None
    assert idx.speaks_of("Mehmet, Ahmet'in kuzeni değil artık.") == "relationship"
    # Not about their relationship, or about other people.
    assert idx.speaks_of("Mehmet'e selam söyleyin.") is None
    assert idx.speaks_of("Ahmet'in kuzeni Zeynep.") is None
    assert index(storage).speaks_of("Kuzeniniz Zeynep nasıl?") is None


def test_one_forgotten_relationship(storage: StorageHandle, world: World) -> None:
    rid = run(storage, lambda c: relationships.gs.relationships_between(
        c, world["ahmet"], world["zeynep"]))[0].id  # fmt: skip
    run(storage, lambda c: relationships.forget_relationships(c, [rid]))
    idx = index(storage)
    assert idx.speaks_of("Zeynep, Ahmet'in kuzeni.") == "relationship"
    assert idx.speaks_of("Mehmet, Ahmet'in kardeşi.") is None


def test_a_forgotten_value(storage: StorageHandle, world: World) -> None:
    mid = run(storage, lambda c: fact(c, world["ahmet2"], "occupation", "avukat"))
    mine = run(storage, lambda c: fact(c, None, "employer", "Kervan Lojistik"))
    run(storage, lambda c: service.forget_memories(c, [mid, mine]))
    idx = index(storage)
    assert idx.speaks_of("Ahmet avukat olarak çalışıyor.") == "value"
    assert idx.speaks_of("Kervan Lojistik'te çalışıyordunuz.") == "value"
    assert idx.speaks_of("Avukatlar çok çalışır.") is None  # nobody in play has it
    assert idx.speaks_of("Lojistik sektörü büyüyor.") is None  # part of the value only
    # The user brings it up: answering it is not using what was forgotten.
    said = index(storage, "Kervan Lojistik'ten ayrıldım, biliyorsun.")
    assert said.speaks_of("Kervan Lojistik'ten ayrıldığınızı söylediniz.") is None


def test_saving_it_again_clears_the_mark(storage: StorageHandle, world: World) -> None:
    mine = run(storage, lambda c: fact(c, None, "employer", "Kervan Lojistik"))
    run(storage, lambda c: service.forget_memories(c, [mine]))
    again = Candidate(predicate="employer", value="Kervan Lojistik",
                      statement="Kervan Lojistik'te çalışıyorum.", about="user")  # fmt: skip
    run(storage, lambda c: service.apply_candidates(c, [again], source=Source("user_edit"),
                                                    explicit=True))  # fmt: skip
    assert index(storage).speaks_of("Kervan Lojistik'te çalışıyorsunuz.") is None


@pytest.mark.parametrize("chunk", [0, 1, 5])
def test_the_guard_drops_what_was_forgotten(
    storage: StorageHandle, world: World, chunk: int
) -> None:
    run(storage, lambda c: relationships.forget_pair(c, world["ahmet"], world["mehmet"]))
    message = "Mehmet, Ahmet'in neyi oluyor?"
    ctx = run(storage, lambda c: people.build(c, (), message, asking=True))
    reply = ("Hangi Ahmet'ten bahsettiğinizi netleştirebilir misiniz efendim? Kayıtlarımda "
             "çocukluk arkadaşınız olan Ahmet bulunuyor; Mehmet bu kişilerden hangisinin kuzeniydi?")  # fmt: skip
    out, removed = guarded(reply, ctx, chunk)
    assert out == ("Hangi Ahmet'ten bahsettiğinizi netleştirebilir misiniz efendim? Kayıtlarımda "
                   "çocukluk arkadaşınız olan Ahmet bulunuyor;")  # fmt: skip
    assert removed == {"forgotten_relationship": 1}
    out, _ = guarded("Mehmet, Ahmet'in kuzeni.", ctx, chunk)
    assert out == people.NO_RECORD


def test_forgotten_checks_only_when_it_matters(storage: StorageHandle, world: World) -> None:
    run(storage, lambda c: relationships.forget_pair(c, world["ahmet"], world["mehmet"]))
    # A statement naming nobody stored: nothing to hold.
    ctx = run(storage, lambda c: people.build(c, (), "Bugün hava güzel.", asking=False))
    assert not ctx.active
    ctx = run(storage, lambda c: people.build(c, (), "Mehmet aradı.", asking=False))
    assert ctx.active
