"""Jobs and workplaces over time (Phase 9.1): a job the user (or a friend) left becomes history,
two jobs said together are both current, a job named without a change word is asked about.
Scripted model answers (the failing one is what real Gemma proposed in Phase 6 sessions
3.memory), production engine, encrypted database; synthetic data only."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazis.storage import StorageHandle
from tests.learning_support import Brain, converse, item, rel

DEV = "Yazılım geliştiricisiyim."
DEV_ITEM = item("Yazılım geliştiricisiyim", "occupation", "yazılım geliştiricisi")
AHMET = "Arkadaşım Ahmet yazılım geliştiricisi."
AHMET_ITEMS = ([item("Ahmet yazılım geliştiricisi", "occupation", "yazılım geliştiricisi", entity="Ahmet")],
               [rel("Arkadaşım Ahmet", "", "friend", "Ahmet")])  # fmt: skip
RESTAURANT = "Ahmet artık yazılım geliştirmiyor, kendi restoranını açtı."


def test_a_friend_who_stopped_developing_is_no_developer_now(
    tmp_path: Path, storage: StorageHandle
) -> None:
    # Phase 6 sessions 3.memory, failing runs: one item, the old value — it became evidence and
    # stayed current.
    only_old = [item("Ahmet artık yazılım geliştirmiyor", "occupation", "yazılım geliştiricisi",
                     entity="Ahmet", change=True)]  # fmt: skip
    s = converse(tmp_path, storage, [AHMET, RESTAURANT],
                 Brain(answers={AHMET: AHMET_ITEMS, RESTAURANT: (only_old, [])}))  # fmt: skip
    assert s.values("Ahmet", "occupation") == set()
    assert s.values("Ahmet", "occupation", "superseded") == {"yazılım geliştiricisi"}


def test_a_friend_with_a_new_job_has_it_current(tmp_path: Path, storage: StorageHandle) -> None:
    both = [item("Ahmet artık yazılım geliştirmiyor", "occupation", "yazılım geliştiricisi",
                 entity="Ahmet", change=True),
            item("kendi restoranını açtı", "occupation", "restoran işletmecisi", entity="Ahmet",
                 change=True)]  # fmt: skip
    s = converse(tmp_path, storage, [AHMET, RESTAURANT],
                 Brain(answers={AHMET: AHMET_ITEMS, RESTAURANT: (both, [])}))  # fmt: skip
    assert s.values("Ahmet", "occupation") == {"restoran işletmecisi"}
    assert s.values("Ahmet", "occupation", "superseded") == {"yazılım geliştiricisi"}


@pytest.mark.parametrize(
    ("said", "items"),
    [
        ("Artık ürün yöneticisi olarak çalışıyorum.",
         [item("Artık ürün yöneticisi olarak çalışıyorum", "occupation", "ürün yöneticisi", change=True)]),
        ("Ürün yöneticisi görevine geçtim.",
         [item("Ürün yöneticisi görevine geçtim", "occupation", "ürün yöneticisi", change=True)]),
        ("Ürün yöneticisi olarak çalışmaya başladım.",
         [item("Ürün yöneticisi olarak çalışmaya başladım", "occupation", "ürün yöneticisi", change=True)]),
        # Both orders of the model's two items.
        ("Yazılım geliştiriciliğini bıraktım, artık ürün yöneticisiyim.",
         [item("Yazılım geliştiriciliğini bıraktım", "occupation", "yazılım geliştiricisi"),
          item("artık ürün yöneticisiyim", "occupation", "ürün yöneticisi", change=True)]),
        ("Yazılım geliştiriciliğini bıraktım, artık ürün yöneticisiyim.",
         [item("artık ürün yöneticisiyim", "occupation", "ürün yöneticisi", change=True),
          item("Yazılım geliştiriciliğini bıraktım", "occupation", "yazılım geliştiricisi")]),
    ],
)  # fmt: skip
def test_a_job_change_makes_the_old_job_history(
    tmp_path: Path, storage: StorageHandle, said: str, items: list
) -> None:
    s = converse(tmp_path, storage, [DEV, said],
                 Brain(answers={DEV: ([DEV_ITEM], []), said: (items, [])}))  # fmt: skip
    assert s.values("user", "occupation") == {"ürün yöneticisi"}
    assert s.values("user", "occupation", "superseded") == {"yazılım geliştiricisi"}
    assert s.inbox == []


def test_two_jobs_said_together_are_both_current(tmp_path: Path, storage: StorageHandle) -> None:
    said = "Yazılım geliştiricisiyim, ayrıca eğitmenlik yapıyorum."
    items = [item("Yazılım geliştiricisiyim", "occupation", "yazılım geliştiricisi"),
             item("eğitmenlik yapıyorum", "occupation", "eğitmen")]  # fmt: skip
    s = converse(tmp_path, storage, [said], Brain(answers={said: (items, [])}))
    assert s.values("user", "occupation") == {"yazılım geliştiricisi", "eğitmen"}
    assert s.inbox == []


@pytest.mark.parametrize("said", ["Eğitmenlik de yapıyorum.", "Ayrıca eğitmenlik yapıyorum.",
                                  "Aynı zamanda eğitmenlik yapıyorum."])  # fmt: skip
def test_a_second_job_said_later_is_current_next_to_the_first(
    tmp_path: Path, storage: StorageHandle, said: str
) -> None:
    second = [item(said.rstrip("."), "occupation", "eğitmen")]
    s = converse(tmp_path, storage, [DEV, said],
                 Brain(answers={DEV: ([DEV_ITEM], []), said: (second, [])}))  # fmt: skip
    assert s.values("user", "occupation") == {"yazılım geliştiricisi", "eğitmen"}
    assert s.inbox == []


def test_a_past_job_mentioned_is_history_and_today_stays(
    tmp_path: Path, storage: StorageHandle
) -> None:
    said = "Eskiden öğretmendim."
    s = converse(tmp_path, storage, [DEV, said],
                 Brain(answers={DEV: ([DEV_ITEM], []),
                                said: ([item("Eskiden öğretmendim", "occupation", "öğretmen")], [])}))  # fmt: skip
    assert s.values("user", "occupation") == {"yazılım geliştiricisi"}
    assert s.values("user", "occupation", "superseded") == {"öğretmen"}


def test_a_job_named_without_a_change_word_is_asked_about(
    tmp_path: Path, storage: StorageHandle
) -> None:
    said = "Öğretmenim."
    s = converse(tmp_path, storage, [DEV, said],
                 Brain(answers={DEV: ([DEV_ITEM], []),
                                said: ([item("Öğretmenim", "occupation", "öğretmen", change=True)], [])}))  # fmt: skip
    assert s.values("user", "occupation") == {"yazılım geliştiricisi"}  # not replaced unasked
    assert [i["type"] for i in s.inbox] == ["conflict"]


KERVAN = "Kervan'da çalışıyorum."
KERVAN_ITEM = item("Kervan'da çalışıyorum", "employer", "Kervan")


@pytest.mark.parametrize(
    ("said", "items", "current", "history"),
    [
        ("Eskiden Kervan'da çalışıyordum, artık Atlas'ta çalışıyorum.",
         [item("Eskiden Kervan'da çalışıyordum", "employer", "Kervan"),
          item("artık Atlas'ta çalışıyorum", "employer", "Atlas", change=True)], {"Atlas"}, {"Kervan"}),
        ("Kervan'dan ayrıldım.", [item("Kervan'dan ayrıldım", "employer", "Kervan")], set(), {"Kervan"}),
        ("Atlas'ta işe başladım.", [item("Atlas'ta işe başladım", "employer", "Atlas", change=True)],
         {"Atlas"}, {"Kervan"}),
        ("Hâlâ Kervan'da çalışıyorum.", [item("Hâlâ Kervan'da çalışıyorum", "employer", "Kervan")],
         {"Kervan"}, set()),
        ("Artık Kervan'da çalışmıyorum.", [item("Artık Kervan'da çalışmıyorum", "employer", "Kervan")],
         set(), {"Kervan"}),
    ],
)  # fmt: skip
def test_workplaces_over_time(tmp_path: Path, storage: StorageHandle, said: str, items: list,
                              current: set[str], history: set[str]) -> None:  # fmt: skip
    s = converse(tmp_path, storage, [KERVAN, said],
                 Brain(answers={KERVAN: ([KERVAN_ITEM], []), said: (items, [])}))  # fmt: skip
    assert s.values("user", "employer") == current
    assert s.values("user", "employer", "superseded") == history


def test_a_friend_who_left_medicine(tmp_path: Path, storage: StorageHandle) -> None:
    first, said = "Komşum Ahmet doktor.", "Ahmet doktorluğu bıraktı."
    s = converse(tmp_path, storage, [first, said], Brain(answers={
        first: ([item("Ahmet doktor", "occupation", "doktor", entity="Ahmet")],
                [rel("Komşum Ahmet", "", "neighbor", "Ahmet")]),
        said: ([item("Ahmet doktorluğu bıraktı", "occupation", "doktor", entity="Ahmet")], []),
    }))  # fmt: skip
    assert s.values("Ahmet", "occupation") == set()
    assert s.values("Ahmet", "occupation", "superseded") == {"doktor"}


def test_an_updated_age_replaces_the_old_one(tmp_path: Path, storage: StorageHandle) -> None:
    first, said = "34 yaşındayım.", "Benim hakkımda bildiklerini güncelle: 35 yaşındayım."
    s = converse(tmp_path, storage, [first, said], Brain(answers={
        first: ([item("34 yaşındayım", "family", "34 yaşında")], []),
        said: ([item("35 yaşındayım", "family", "35", change=True)], []),
    }))  # fmt: skip
    assert s.values("user", "age") == {"35"}
    assert s.values("user", "age", "superseded") == {"34"}
    assert s.values("user", "family") == set()


def test_a_leaving_is_not_the_new_job(tmp_path: Path, storage: StorageHandle) -> None:
    # Phase 9.1 run 2 (t15): the model gave the leaving itself as Ahmet's current job.
    first, said = "Komşum Ahmet doktor.", "Ahmet doktorluğu bıraktı."
    s = converse(tmp_path, storage, [first, said], Brain(answers={
        first: ([item("Ahmet doktor", "occupation", "doktor", entity="Ahmet")],
                [rel("Komşum Ahmet", "", "neighbor", "Ahmet")]),
        said: ([item("Ahmet doktorluğu bıraktı", "occupation", "doktor", entity="Ahmet"),
                item("Ahmet doktorluğu bıraktı", "occupation", "doktorluğu bıraktı", entity="Ahmet",
                     change=True)], []),
    }))  # fmt: skip
    assert s.values("Ahmet", "occupation") == set()
    assert s.values("Ahmet", "occupation", "superseded") == {"doktor"}


def test_only_the_leaving_given_ends_the_job_it_names(
    tmp_path: Path, storage: StorageHandle
) -> None:
    # Phase 9.1 runs 2 and 3 (t15): one item, the leaving itself — it must still end "doktor".
    first, said = "Komşum Ahmet doktor.", "Ahmet doktorluğu bıraktı."
    s = converse(tmp_path, storage, [first, said], Brain(answers={
        first: ([item("Ahmet doktor", "occupation", "doktor", entity="Ahmet")],
                [rel("Komşum Ahmet", "", "neighbor", "Ahmet")]),
        said: ([item("Ahmet doktorluğu bıraktı", "occupation", "doktorluğu bıraktı", entity="Ahmet",
                     change=True)], []),
    }))  # fmt: skip
    assert s.values("Ahmet", "occupation") == set()
    assert s.values("Ahmet", "occupation", "superseded") == {"doktor"}


def test_a_leaving_that_names_nothing_stored_writes_nothing(
    tmp_path: Path, storage: StorageHandle
) -> None:
    said = "Muhasebeciliği bıraktım."
    s = converse(tmp_path, storage, [said], Brain(answers={
        said: ([item("Muhasebeciliği bıraktım", "occupation", "muhasebeciliği bıraktım")], []),
    }))  # fmt: skip
    assert [f for f in s.facts if f["predicate"] == "occupation"] == []


def test_the_job_in_other_words_ends_the_stored_one(tmp_path: Path, storage: StorageHandle) -> None:
    # Phase 9.1 run 4 (t15): the model gave "doktorluk" for "Ahmet doktorluğu bıraktı".
    first, said = "Komşum Ahmet doktor.", "Ahmet doktorluğu bıraktı."
    s = converse(tmp_path, storage, [first, said], Brain(answers={
        first: ([item("Ahmet doktor", "occupation", "doktor", entity="Ahmet")],
                [rel("Komşum Ahmet", "", "neighbor", "Ahmet")]),
        said: ([item("Ahmet doktorluğu bıraktı", "occupation", "doktorluk", entity="Ahmet")], []),
    }))  # fmt: skip
    assert s.values("Ahmet", "occupation") == set()
    assert s.values("Ahmet", "occupation", "superseded") == {"doktor"}
