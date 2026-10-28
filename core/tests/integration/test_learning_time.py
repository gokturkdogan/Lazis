"""Past, current and future in background learning, end to end (Phase 9, test group B, part 2):
a past value becomes history and never replaces today's, a future one a plan, a past
relationship is ended; a time the user named is kept as written; a passing state is not
kept. Scripted model, production engine, encrypted database; synthetic data only."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazis.storage import StorageHandle
from tests.learning_support import Brain, converse, item, rel

# (predicate, past value, current value, sentence)
PAIRS = [
    ("occupation", "öğretmen", "yazılım geliştiricisi",
     "Eskiden öğretmendim, artık yazılım geliştiricisiyim."),
    ("occupation", "garson", "mimar", "Öğrenciyken garsonluk yapıyordum, şimdi mimarım."),
    ("location", "Ankara", "İstanbul", "Önceden Ankara'da yaşıyordum, şimdi İstanbul'dayım."),
    ("location", "Rize", "Bursa", "Çocukken Rize'de yaşardık, artık Bursa'dayız."),
    ("employer", "Kervan Lojistik", "Pusula Yazılım",
     "Geçen yıl Kervan Lojistik'te çalışıyordum, artık Pusula Yazılım'dayım."),
    ("employer", "Atlas", "Martı", "Eskiden Atlas'ta çalışıyordum, şimdi Martı'dayım."),
    ("phone", "Pixel 6", "iPhone 15", "Eskiden Pixel 6 kullanıyordum, artık iPhone 15 kullanıyorum."),
    ("computer", "ThinkPad", "MacBook Pro",
     "Önceden ThinkPad kullanıyordum, şimdi MacBook Pro kullanıyorum."),
]  # fmt: skip


def _quote(sentence: str, value: str) -> str:
    for clause in sentence.rstrip(".").split(", "):
        if value.split()[0] in clause:
            return clause
    return sentence


@pytest.mark.parametrize(("predicate", "old", "new", "sentence"), PAIRS)
@pytest.mark.parametrize("stored_before", [False, True])
def test_past_and_current_in_one_sentence(
    tmp_path: Path, storage: StorageHandle, predicate: str, old: str, new: str, sentence: str,
    stored_before: bool,
) -> None:  # fmt: skip
    turns, answers = [sentence], {sentence: ([
        item(_quote(sentence, old), predicate, old),
        item(_quote(sentence, new), predicate, new, change=True),
    ], [])}  # fmt: skip
    if stored_before:  # the old value was learned earlier as current
        earlier = f"{old} bilgisi doğru."
        turns.insert(0, earlier)
        answers[earlier] = ([item(earlier, predicate, old)], [])
    s = converse(tmp_path, storage, turns, Brain(answers=answers))
    assert s.values("user", predicate) == {new}  # today's value
    assert old in s.values("user", predicate, "superseded")  # history, kept
    assert len([f for f in s.facts if f["predicate"] == predicate and f["value"] == old]) == 1


@pytest.mark.parametrize(
    ("sentence", "predicate", "value"),
    [
        ("Gelecek yıl İzmir'e taşınacağım.", "location", "İzmir"),
        ("Seneye Pusula Yazılım'da çalışacağım.", "employer", "Pusula Yazılım"),
        ("Yakında yeni bir telefon alacağım, iPhone 16.", "phone", "iPhone 16"),
        ("Haftaya mimar olarak başlayacağım.", "occupation", "mimar"),
    ],
)
def test_a_future_value_is_a_plan_not_today(tmp_path: Path, storage: StorageHandle,
                                            sentence: str, predicate: str, value: str) -> None:  # fmt: skip
    s = converse(tmp_path, storage, [sentence],
                 Brain(answers={sentence: ([item(sentence.rstrip("."), predicate, value)], [])}))  # fmt: skip
    assert s.values("user", predicate) == set()
    assert len(s.values("user", "plan")) == 1


@pytest.mark.parametrize(
    ("sentence", "past_target", "current_target"),
    [
        ("Geçen yıl Kervan Lojistik'te çalışıyordum, artık Pusula Yazılım'dayım.",
         "Kervan Lojistik", "Pusula Yazılım"),
        ("Eskiden Atlas'ta çalışıyordum, şimdi Martı'dayım.", "Atlas", "Martı"),
    ],
)  # fmt: skip
@pytest.mark.parametrize("model_statuses", [("active", "active"), ("active", "ended"),
                                            ("ended", "ended")])  # fmt: skip
def test_relationship_status_follows_the_users_words(
    tmp_path: Path, storage: StorageHandle, sentence: str, past_target: str,
    current_target: str, model_statuses: tuple[str, str],
) -> None:  # fmt: skip
    """The model's own status is corrected when the words are clear (it was seen reversed)."""
    whole = sentence.rstrip(".")
    answers = {sentence: ([], [
        rel(whole, "", "works_at", past_target, status=model_statuses[0]),
        rel(whole, "", "works_at", current_target, status=model_statuses[1]),
    ])}  # fmt: skip
    s = converse(tmp_path, storage, [sentence], Brain(answers=answers))
    assert s.rel("user", "works_at", current_target, "active")
    assert s.rel("user", "works_at", past_target, "ended")


@pytest.mark.parametrize(
    ("sentence", "predicate", "value"),
    [
        ("Bugün çok yorgunum.", "note", "yorgun"),
        ("Şu an canım pizza istiyor.", "likes", "pizza"),
        ("Bu akşam film izlemek istiyorum.", "interest", "film"),
        ("Bugün kahve içmek hoşuma gitti.", "likes", "kahve"),
    ],
)
def test_a_passing_state_is_not_kept(tmp_path: Path, storage: StorageHandle, sentence: str,
                                     predicate: str, value: str) -> None:  # fmt: skip
    s = converse(tmp_path, storage, [sentence],
                 Brain(answers={sentence: ([item(sentence.rstrip("."), predicate, value)], [])}))  # fmt: skip
    assert s.facts == []


@pytest.mark.parametrize(
    ("sentence", "predicate", "value"),
    [
        ("Sıcaktan hiç hoşlanmam.", "dislikes", "sıcak"),
        ("Her sabah kahve içerim.", "habit", "her sabah kahve"),
        ("Genelde akşamları kitap okurum.", "habit", "akşamları kitap"),
    ],
)
def test_a_lasting_one_is_kept(tmp_path: Path, storage: StorageHandle, sentence: str,
                               predicate: str, value: str) -> None:  # fmt: skip
    s = converse(tmp_path, storage, [sentence],
                 Brain(answers={sentence: ([item(sentence.rstrip("."), predicate, value)], [])}))  # fmt: skip
    assert s.values("user", predicate) == {value}


@pytest.mark.parametrize(
    ("sentence", "who", "predicate", "value", "when"),
    [
        ("Mehmet 2024'te İzmir'e taşındı.", "Mehmet", "location", "İzmir", "2024'te"),
        ("LAZIS projesini geçen ay başlattım.", "user", "event", "LAZIS projesini başlattım",
         "geçen ay"),
        ("Üç yıl önce Konya'dan İzmir'e taşındım.", "user", "location", "İzmir", "Üç yıl önce"),
        ("İzmir'de yaşıyorum.", "user", "location", "İzmir", None),
    ],
)  # fmt: skip
def test_the_time_named_is_kept_as_written_never_a_date(
    tmp_path: Path, storage: StorageHandle, sentence: str, who: str, predicate: str, value: str,
    when: str | None,
) -> None:  # fmt: skip
    entity = "" if who == "user" else who
    s = converse(tmp_path, storage, [sentence], Brain(answers={sentence: (
        [item(sentence.rstrip("."), predicate, value, entity=entity, change=True)], [])}))  # fmt: skip
    (f,) = [f for f in s.facts if f["predicate"] == predicate]
    assert f["status"] == "active"
    assert (f["event_time"] or "").casefold() == (when or "").casefold()


# The two answers Gemma gave in the Phase 9 evaluation, as given (seen: Atlas ended by "Kervan'da
# çalışmıyorum"; Kervan left current by "Kervan'dan ayrıldım").
def _neg(quote: str, target: str) -> dict[str, object]:
    return {**rel(quote, "", "works_at", target, status="ended", change=True), "negated": True}


@pytest.mark.parametrize("first_as", ["fact", "relationship"])
def test_ending_one_workplace_never_ends_the_new_one(tmp_path: Path, storage: StorageHandle,
                                                     first_as: str) -> None:  # fmt: skip
    first, then = (
        "Kervan Lojistik'te çalışıyorum.",
        ("Artık Kervan Lojistik'te çalışmıyorum, Atlas Yazılım'a geçtim."),
    )
    earlier = (([item(first, "employer", "Kervan Lojistik")], []) if first_as == "fact" else
               ([], [rel(first, "", "works_at", "Kervan Lojistik")]))  # fmt: skip
    new = item("Atlas Yazılım'a geçtim", "employer", "Atlas Yazılım", change=True)
    new["replaces"] = "Kervan Lojistik"
    answers = {first: earlier,
               then: ([new], [_neg("Kervan Lojistik'te çalışmıyorum", "Kervan Lojistik")])}  # fmt: skip
    s = converse(tmp_path, storage, [first, then], Brain(answers=answers))
    assert s.values("user", "employer") == {"Atlas Yazılım"}
    assert s.rel("user", "works_at", "Atlas Yazılım", "active")
    assert not s.rel("user", "works_at", "Kervan Lojistik", "active")
    assert s.rel("user", "works_at", "Kervan Lojistik", "ended")
    kervan = [r for r in s.relationships if r["target"] == "Kervan Lojistik"]
    assert len(kervan) == 1  # ended once, not a second ended copy


@pytest.mark.parametrize(
    ("first", "then", "old", "new"),
    [
        ("Kervan'da çalışıyorum.", "Kervan'dan ayrıldım, artık Atlas'tayım.", "Kervan", "Atlas"),
        ("Pusula'da çalışıyorum.", "Pusula'dan istifa ettim, şimdi Martı'dayım.", "Pusula",
         "Martı"),
        ("Ankara'da yaşıyorum.", "Ankara'dan ayrıldım; artık İzmir'deyim.", "Ankara", "İzmir"),
    ],
)  # fmt: skip
def test_the_place_left_becomes_history(tmp_path: Path, storage: StorageHandle, first: str,
                                        then: str, old: str, new: str) -> None:  # fmt: skip
    pred, type_ = ("location", "lives_in") if old == "Ankara" else ("employer", "works_at")
    stale = item(then.rstrip("."), pred, old, change=True)  # the model kept the old one
    answers = {first: ([item(first.rstrip("."), pred, old)], []),
               then: ([stale], [rel(then.rstrip("."), "", type_, new, change=True)])}  # fmt: skip
    s = converse(tmp_path, storage, [first, then], Brain(answers=answers))
    assert s.values("user", pred) == {new}
    assert old in s.values("user", pred, "superseded")
    assert s.rel("user", type_, new, "active")


@pytest.mark.parametrize(
    ("sentence", "quote", "who", "predicate", "value"),
    [
        # Phase 6 gold E5: "bugün" is when Ahmet called; joining the club lasts.
        ("Ahmet bugün aradı, satranç kulübüne yazılmış.", "satranç kulübüne yazılmış", "Ahmet",
         "interest", "satranç kulübü"),
        ("Bugün Elif'le konuştum, yogaya başlamış.", "yogaya başlamış", "Elif", "interest",
         "yoga"),
    ],
)  # fmt: skip
def test_today_about_something_else_does_not_make_a_fact_passing(
    tmp_path: Path, storage: StorageHandle, sentence: str, quote: str, who: str, predicate: str,
    value: str,
) -> None:  # fmt: skip
    answers = {sentence: ([item(quote, predicate, value, entity=who)], [])}
    s = converse(tmp_path, storage, [sentence], Brain(answers=answers))
    assert s.values(who, predicate) == {value}


@pytest.mark.parametrize(
    ("sentence", "when"),
    [("Seneye emekli olacağım.", "Seneye"), ("Gelecek yıl maraton koşacağım.", "Gelecek yıl")],
)
def test_a_dated_intention_is_a_plan_with_the_users_time(tmp_path: Path, storage: StorageHandle,
                                                         sentence: str, when: str) -> None:  # fmt: skip
    answers = {sentence: ([item(sentence.rstrip("."), "goal", "emekli olmak")], [])}
    s = converse(tmp_path, storage, [sentence], Brain(answers=answers))
    (f,) = s.facts
    assert f["predicate"] == "plan" and f["event_time"] == when


def test_an_undated_wish_stays_a_goal(tmp_path: Path, storage: StorageHandle) -> None:
    sentence = "Bir gün kendi şirketimi kuracağım."
    answers = {sentence: ([item(sentence.rstrip("."), "goal", "kendi şirketini kurmak")], [])}
    s = converse(tmp_path, storage, [sentence], Brain(answers=answers))
    assert s.values("user", "goal") == {"kendi şirketini kurmak"}


def test_a_divorce_ends_the_marriage(tmp_path: Path, storage: StorageHandle) -> None:
    """Phase 7 gold T2, Gemma's answer as given: ex_spouse "ended" with change."""
    first, then = "Derya ile Kaan evli.", "Derya ile Kaan geçen ay boşandılar."
    ex = {**rel(then, "Derya", "ex_spouse", "Kaan", status="ended", change=True),
          "time": "geçen ay"}  # fmt: skip
    answers = {first: ([], [rel(first, "Derya", "spouse", "Kaan")]), then: ([], [ex])}
    s = converse(tmp_path, storage, [first, then], Brain(answers=answers))
    assert not s.rel("Derya", "spouse", "Kaan", "active")


def test_a_past_habit_given_up_is_history(tmp_path: Path, storage: StorageHandle) -> None:
    sentence = "Eskiden sigara içerdim, bıraktım."
    answers = {sentence: ([item(sentence.rstrip("."), "habit", "sigara içmek")], [])}
    s = converse(tmp_path, storage, [sentence], Brain(answers=answers))
    assert s.values("user", "habit") == set()
    assert s.values("user", "habit", "superseded") == {"sigara içmek"}
