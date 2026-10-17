"""Summary verification: every kept item must be backed by the original messages.

Covers the failure modes named for Phase 3: attributing LAZIS's words to the user, invented
facts, stale decisions shown as current, mixed-up people, mis-associated dates.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from lazis.conversation.compaction import (
    build_messages,
    chunk_messages,
    normalize,
    parse_summary,
    plan_split,
    quote_in,
    render,
    verify_and_render,
    verify_items,
)
from lazis.conversation.context import TokenEstimator
from lazis.conversation.models import Message

EST = TokenEstimator(2.2, 8)

CONVO = [
    ("user", "Kız kardeşim Ayşe 3 Kasım'da Ankara'ya taşınıyor, ona yardım etmek istiyorum."),
    (
        "assistant",
        "Taşınma için bir kontrol listesi hazırlayabilirim. Belki nakliye firması tutarsınız.",
    ),
    ("user", "Toplantıyı salıya alalım dedik ama sonra perşembeye kaydırdık."),
    ("assistant", "Anladım, perşembe olarak not ettim."),
    ("user", "İş arkadaşım Mehmet de 10 Kasım'da İzmir'e gidecek, galiba."),
    ("assistant", "Mehmet için de hatırlatma ekleyebilirim."),
]


def messages() -> dict[int, Message]:
    out: dict[int, Message] = {}
    for i, (role, content) in enumerate(CONVO, start=1):
        out[i] = Message(
            f"m{i}",
            "c1",
            i,
            role,
            content,
            None,
            "complete",
            None,
            None,
            None,  # type: ignore[arg-type]
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            "t",
            "t",
            i,
        )
    return out


def item(
    text: str, source: str, refs: list[int], quote: str, certain: bool = True, **kw: Any
) -> dict[str, Any]:
    return {"text": text, "source": source, "refs": refs, "quote": quote, "certain": certain, **kw}


def empty() -> dict[str, list[Any]]:
    return {
        k: []
        for k in (
            "goals",
            "topics",
            "decisions",
            "open_questions",
            "constraints",
            "people",
            "instructions",
            "assistant_notes",
        )
    }


def test_faithful_items_are_kept() -> None:
    raw = empty()
    raw["goals"] = [
        item("Ayşe'nin taşınmasına yardım etmek", "user", [1], "ona yardım etmek istiyorum")
    ]
    clean, kept, dropped = verify_items(raw, messages(), covered_to=6)
    assert (kept, dropped) == (1, 0) and clean["goals"][0]["refs"] == [1]


def test_lazis_suggestion_attributed_to_the_user_is_dropped() -> None:
    raw = empty()
    # The nakliye idea came from LAZIS (#2); claiming the user decided it must fail.
    raw["decisions"] = [
        item("Nakliye firması tutulacak", "user", [2], "nakliye firması tutarsınız", current=True)
    ]
    _, kept, dropped = verify_items(raw, messages(), covered_to=6)
    assert (kept, dropped) == (0, 1)
    # Correctly attributed, it survives — and is rendered apart from the user's own words.
    raw["decisions"] = []
    raw["assistant_notes"] = [
        item("Nakliye firması önerildi", "assistant", [2], "nakliye firması tutarsınız")
    ]
    verified = verify_and_render(raw, messages(), from_seq=1, to_seq=6)
    assert verified.kept == 1
    assert "LAZIS'in önerileri" in verified.rendered and "kullanıcının görüşü" in verified.rendered


def test_invented_fact_without_a_matching_quote_is_dropped() -> None:
    raw = empty()
    raw["goals"] = [item("Ayşe İstanbul'a taşınıyor", "user", [1], "Ayşe İstanbul'a taşınıyor")]
    raw["constraints"] = [item("Bütçe 50 bin TL", "user", [3], "bütçemiz 50 bin lira")]
    _, kept, dropped = verify_items(raw, messages(), covered_to=6)
    assert (kept, dropped) == (0, 2)


def test_references_must_exist_inside_the_summarized_range() -> None:
    raw = empty()
    raw["goals"] = [
        item("x", "user", [99], "ona yardım etmek"),
        item("y", "user", [], "ona yardım etmek"),
        item("z", "user", [5], "İzmir'e gidecek"),
    ]
    _, kept, dropped = verify_items(raw, messages(), covered_to=4)
    assert (kept, dropped) == (0, 3)


def test_people_stay_separate_and_dates_stay_with_their_event() -> None:
    raw = empty()
    raw["people"] = [
        {
            "name": "Ayşe",
            "relation": "kız kardeşi; 3 Kasım'da Ankara'ya taşınıyor",
            "source": "user",
            "refs": [1],
            "quote": "Kız kardeşim Ayşe 3 Kasım'da Ankara'ya",
            "certain": True,
        },
        # Mixing Mehmet's date into Ayşe's message is not supported by message #1.
        {
            "name": "Ayşe",
            "relation": "10 Kasım'da İzmir'e gidiyor",
            "source": "user",
            "refs": [1],
            "quote": "10 Kasım'da İzmir'e gidecek",
            "certain": True,
        },
        {
            "name": "Mehmet",
            "relation": "iş arkadaşı; 10 Kasım'da İzmir'e gidecek",
            "source": "user",
            "refs": [5],
            "quote": "Mehmet de 10 Kasım'da İzmir'e gidecek",
            "certain": False,
        },
    ]
    verified = verify_and_render(raw, messages(), from_seq=1, to_seq=6)
    assert (verified.kept, verified.dropped) == (2, 1)
    assert "- Ayşe: kız kardeşi; 3 Kasım'da Ankara'ya taşınıyor [#1]" in verified.rendered
    assert "- Mehmet: iş arkadaşı; 10 Kasım'da İzmir'e gidecek (belirsiz) [#5]" in verified.rendered


def test_replaced_decisions_are_not_presented_as_current() -> None:
    raw = empty()
    raw["decisions"] = [
        item("Toplantı salı günü", "user", [3], "Toplantıyı salıya alalım dedik", current=False),
        item("Toplantı perşembe günü", "user", [3], "sonra perşembeye kaydırdık", current=True),
    ]
    rendered = verify_and_render(raw, messages(), from_seq=1, to_seq=6).rendered
    current, _, old = rendered.partition("Değiştirilmiş eski kararlar (artık geçerli değil):")
    assert "Toplantı perşembe günü" in current and "salı" not in current
    assert "Toplantı salı günü" in old


def test_uncertain_items_are_marked() -> None:
    raw = empty()
    raw["topics"] = [
        item("Mehmet'in İzmir yolculuğu", "user", [5], "İzmir'e gidecek, galiba", certain=False)
    ]
    assert "(belirsiz)" in verify_and_render(raw, messages(), from_seq=1, to_seq=6).rendered


def test_malformed_items_never_crash_and_are_counted() -> None:
    raw: dict[str, Any] = empty()
    raw["goals"] = ["metin", {"text": 5}, {"source": "user"}, None]
    raw["topics"] = "not a list"
    _, kept, dropped = verify_items(raw, messages(), covered_to=6)
    assert kept == 0 and dropped == 4
    assert parse_summary('```json\n{"goals": []}\n```') == {"goals": []}
    assert parse_summary('önce açıklama {"goals": []} sonra') == {"goals": []}
    assert parse_summary("JSON yok") is None


def test_quote_matching_is_normalized_and_fuzzy_but_strict_enough() -> None:
    text = "İş arkadaşım Mehmet de 10 Kasım'da İzmir'e gidecek, galiba."
    assert quote_in("iş arkadaşım mehmet de 10 kasım da izmir e gidecek", text)
    assert quote_in("İş arkadaşım Mehmet de 10 Kasımda İzmire gidecek", text)  # small differences
    assert not quote_in("Mehmet 12 Aralık'ta Antalya'ya gidecek", text)
    assert normalize("İZMİR'E") == "izmir e"


def test_empty_result_still_renders_an_honest_block() -> None:
    rendered = render(empty(), from_seq=1, to_seq=6)
    assert "doğrulanmış bir bilgi çıkmadı" in rendered


def test_split_keeps_recent_whole_exchanges_verbatim() -> None:
    msgs = [replace(m, token_count=300) for m in messages().values()]
    plan = plan_split(msgs, estimator=EST, keep_recent_tokens=650, keep_recent_messages=2)
    assert (
        plan is not None
        and plan.split_seq == 5
        and [m.seq for m in plan.to_compact] == [1, 2, 3, 4]
    )
    assert (
        plan_split(msgs[:2], estimator=EST, keep_recent_tokens=650, keep_recent_messages=2) is None
    )


def test_long_ranges_are_compacted_in_chunks() -> None:
    msgs = list(messages().values()) * 1
    chunks = chunk_messages(msgs, estimator=EST, max_tokens=80)
    assert len(chunks) > 1 and [m.seq for c in chunks for m in c] == [1, 2, 3, 4, 5, 6]


def test_summary_request_carries_previous_items_and_numbered_transcript() -> None:
    previous = {"goals": [item("eski", "user", [1], "ona yardım")]}
    req = build_messages(previous, list(messages().values())[2:4])
    assert req[0].role == "system" and "KELİMESİ KELİMESİNE" in req[0].content
    assert "Önceki özet" in req[1].content and "#3 KULLANICI: Toplantıyı" in req[1].content
    assert "#4 LAZIS: Anladım" in req[1].content


def test_truncated_json_keeps_only_complete_items() -> None:
    full = (
        '{"goals": [{"text": "a", "source": "user", "refs": [1], "quote": "q", "certain": true},'
        ' {"text": "b", "source": "user", "refs": [1], "quote": "q", "certain": true}],'
        ' "topics": [{"text": "kesik metin'
    )
    data = parse_summary(full)
    assert data is not None and [g["text"] for g in data["goals"]] == ["a", "b"]
    assert "topics" not in data or data["topics"] == []
    # Nothing complete before the cut: nothing to salvage (and no exception).
    assert parse_summary('{"goals": [{"text": "yar') is None
    assert parse_summary("{") is None
