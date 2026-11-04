"""Summary verification: every kept item must be backed by the original messages.

Covers the failure modes named for Phase 3: attributing LAZIS's words to the user, invented
facts, stale decisions shown as current, mixed-up people, mis-associated dates.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from lazis.conversation.compaction import (
    audit_rewrite,
    build_messages,
    chunk_messages,
    normalize,
    parse_kind,
    parse_summary,
    plan_split,
    quote_in,
    render,
    verify_and_render,
    verify_items,
)
from lazis.conversation.context import TokenEstimator
from lazis.conversation.models import Message
from lazis.conversation.prompts import (
    SECTIONS,
    SUMMARY_INSTRUCTIONS,
    SUMMARY_OUTPUT_ORDER,
    SUMMARY_SCHEMA,
)

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


# ----- observation only: what a rewrite may have lost -----------------------------------------
def test_parse_kind_tells_a_cut_output_apart() -> None:
    whole = (
        '{"goals": [{"text": "a", "source": "user", "refs": [1], "quote": "q", "certain": true}]}'
    )
    assert parse_kind(whole) == "complete"
    assert parse_kind(f"```json\n{whole}\n```") == "complete"
    cut = whole[:-2] + ', {"text": "kesik metin'
    assert parse_kind(cut) == "salvaged"
    assert parse_summary(cut) is not None  # the same text is still read as before
    assert parse_kind('{"goals": [{"text": "yar') == "failed"
    assert parse_kind("metin") == "failed"


def test_audit_finds_an_item_the_rewrite_left_out_with_nothing_dropped() -> None:
    """REL-003: the fact is gone, and the evidence check has nothing to count."""
    before = {
        **empty(),
        "goals": [item("Günde 8 bin adım atmak", "user", [1], "ona yardım")],
        "topics": [item("Toplantı perşembe", "user", [3], "perşembeye kaydırdık")],
    }
    after = {**empty(), "topics": [item("Toplantı perşembe", "user", [3], "perşembeye kaydırdık")]}
    verified = verify_and_render(after, messages(), from_seq=1, to_seq=6)
    assert verified.dropped == 0  # the evidence check sees no problem
    audit = audit_rewrite(before, verified.content)
    assert [(x.section, x.source, x.refs) for x in audit.possibly_lost] == [("goals", "user", (1,))]
    assert audit.refs_no_longer_cited == (1,)
    assert audit.lost_by("user") == 1 and audit.lost_by("assistant") == 0


def test_audit_sees_a_lost_detail_when_the_message_is_still_cited() -> None:
    before = {
        **empty(),
        "people": [
            {**item("", "user", [1], "kız kardeşim"), "name": "Ayşe", "relation": "kız kardeşi"}
        ],
    }
    after = {**empty(), "goals": [item("Ayşe taşınıyor", "user", [1], "kız kardeşim")]}
    audit = audit_rewrite(before, after)
    assert audit.refs_no_longer_cited == ()
    assert [x.section for x in audit.possibly_lost] == ["people"]
    assert audit.possibly_lost[0].words_gone == 2 and audit.possibly_lost[0].words_total == 3


def test_a_quote_does_not_count_as_keeping_a_fact() -> None:
    """The quote is not shown to the model in later turns."""
    before = {**empty(), "goals": [item("Bütçe 35 bin", "user", [1], "yardım")]}
    after = {**empty(), "goals": [item("Bütçe belirlendi", "user", [1], "Bütçe 35 bin")]}
    assert audit_rewrite(before, after).lost_by("user") == 1


def test_audit_counts_uncertain_made_certain() -> None:
    before = {**empty(), "topics": [item("Mehmet gidebilir", "user", [5], "galiba", certain=False)]}
    same = {**empty(), "topics": [item("Mehmet gidebilir", "user", [5], "galiba", certain=False)]}
    made_sure = {
        **empty(),
        "topics": [item("Mehmet gidebilir", "user", [5], "galiba", certain=True)],
    }
    assert audit_rewrite(before, same).became_certain == 0
    assert audit_rewrite(before, made_sure).became_certain == 1


def test_audit_of_a_first_version_or_identical_rewrite_finds_nothing() -> None:
    content = {**empty(), "goals": [item("Ayşe taşınıyor", "user", [1], "ona yardım")]}
    assert audit_rewrite(None, content) == audit_rewrite({}, content)
    audit = audit_rewrite(None, content)
    assert (
        audit.possibly_lost == () and audit.refs_no_longer_cited == () and audit.became_certain == 0
    )
    same = audit_rewrite(content, content)
    assert same.possibly_lost == () and same.refs_no_longer_cited == ()


def test_audit_survives_malformed_content_and_keeps_no_text() -> None:
    bad: dict[str, Any] = {"goals": ["metin", {"source": "user", "refs": "x"}], "topics": "yok"}
    assert audit_rewrite(bad, {}).refs_no_longer_cited == ()
    before = {**empty(), "goals": [item("Selin vejetaryen", "user", [1], "yardım")]}
    audit = audit_rewrite(before, empty())
    assert "Selin" not in repr(audit) and "vejetaryen" not in repr(audit)


# ----- the order the model writes in (REL-003, fix 3) -------------------------------------------
def test_the_schema_asks_for_what_the_user_decided_first_and_questions_last() -> None:
    order = list(SUMMARY_SCHEMA["properties"])
    assert order == list(SUMMARY_OUTPUT_ORDER)
    assert SUMMARY_SCHEMA["required"] == order
    critical = ("decisions", "instructions", "constraints", "people")
    assert order[: len(critical)] == list(critical)
    assert order.index("open_questions") > max(
        order.index(k) for k in (*critical, "goals", "topics")
    )
    assert order[-1] == "assistant_notes"


def test_the_writing_order_changes_no_section_and_no_rule() -> None:
    assert sorted(SUMMARY_OUTPUT_ORDER) == sorted(key for key, _ in SECTIONS)
    assert [key for key, _ in SECTIONS][:3] == [
        "goals",
        "topics",
        "decisions",
    ]  # the rendered layout
    decision = SUMMARY_SCHEMA["properties"]["decisions"]["items"]
    assert (
        decision["properties"]["current"] == {"type": "boolean"}
        and "current" in decision["required"]
    )
    person = SUMMARY_SCHEMA["properties"]["people"]["items"]
    assert "name" in person["required"] and "text" not in person["properties"]
    for key in SUMMARY_OUTPUT_ORDER:
        required = SUMMARY_SCHEMA["properties"][key]["items"]["required"]
        assert {"source", "refs", "quote", "certain"} <= set(required)
    assert "1 200" not in SUMMARY_INSTRUCTIONS  # the instructions set no limit of their own


def test_a_cut_in_the_new_order_keeps_what_the_user_decided_and_loses_the_questions() -> None:
    whole = {key: [] for key in SUMMARY_OUTPUT_ORDER} | {
        "decisions": [item("Perşembe", "user", [3], "perşembeye kaydırdık", current=True)],
        "people": [
            {
                **item("", "user", [5], "İş arkadaşım Mehmet"),
                "name": "Mehmet",
                "relation": "iş arkadaşı",
            }
        ],
        "open_questions": [
            item("Ne zaman", "user", [1], "ona yardım"),
            item("Nerede", "user", [1], "ona yardım"),
        ],
    }
    text = json.dumps(whole, ensure_ascii=False)
    cut = text[: text.index("Nerede")]
    assert parse_kind(cut) == "salvaged"
    parsed = parse_summary(cut)
    assert parsed is not None
    verified = verify_and_render(parsed, messages(), from_seq=1, to_seq=6)
    assert verified.content["decisions"] and verified.content["people"]
    assert [i["text"] for i in verified.content["open_questions"]] == ["Ne zaman"]


def test_rendering_does_not_depend_on_the_order_items_arrive_in() -> None:
    raw = {
        **empty(),
        "goals": [item("Yardım", "user", [1], "ona yardım")],
        "decisions": [item("Perşembe", "user", [3], "perşembeye kaydırdık", current=True)],
        "people": [
            {
                **item("", "user", [5], "İş arkadaşım Mehmet"),
                "name": "Mehmet",
                "relation": "iş arkadaşı",
            }
        ],
    }
    reordered = {key: raw[key] for key in SUMMARY_OUTPUT_ORDER}
    a = verify_and_render(raw, messages(), from_seq=1, to_seq=6)
    b = verify_and_render(reordered, messages(), from_seq=1, to_seq=6)
    assert a.rendered == b.rendered and a.kept == b.kept == 3
    assert (
        a.rendered.index("hedefler") < a.rendered.index("kararları") < a.rendered.index("kişiler")
    )


def test_a_summary_written_in_the_old_order_is_still_read_and_used_as_previous() -> None:
    old_order = {key: [] for key, _ in SECTIONS} | {
        "goals": [item("Yardım", "user", [1], "ona yardım")]
    }
    text = json.dumps(old_order, ensure_ascii=False)
    assert parse_kind(text) == "complete"
    verified = verify_and_render(parse_summary(text) or {}, messages(), from_seq=1, to_seq=6)
    assert verified.kept == 1
    request = build_messages(verified.content, list(messages().values())[2:4])
    assert "Önceki özet" in request[1].content
