"""Extraction instruction, schema and validation (pure). Synthetic data only."""

from __future__ import annotations

import json
import re
from typing import Any

from lazis.memory import extraction, registry, text
from lazis.memory.extraction import Known, Target
from lazis.memory.models import Entity

T1 = Target("m1", "MSG1", "Ben artık İzmir'de yaşıyorum, Ahmet'le de dün görüştüm.")
T2 = Target("m2", "MSG2", "Proje LAZIS'te artık FastAPI kullanıyoruz.")
AHMET = Entity("E-ahmet", "person", "Ahmet", "ahmet", "çocukluk arkadaşı", None, None, "active",
               None, "t", "t", ("Ahmet",))  # fmt: skip


def item(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "message": "m1", "quote": "artık İzmir'de yaşıyorum", "entity": "", "relation": "",
        "predicate": "location", "value": "İzmir", "statement": "Kullanıcı İzmir'de yaşıyor.",
        "change": True, "replaces": "", "certain": True, "sensitive": "", "importance": 0.7,
    }  # fmt: skip
    base.update(kw)
    return base


def test_instruction_quotes_targets_and_lists_context() -> None:
    known = [Known(AHMET, ("meslek: yazılımcı",))]
    out = extraction.build_instruction(
        [T1, T2],
        known=known,
        user_facts=["yaşadığı yer (şehir): Ankara"],
        forgotten=["Ahmet — meslek"],
    )
    assert out.startswith("[LAZIS İÇ GÖREVİ")
    assert "[m1] «Ben artık İzmir'de" in out and "[m2] «Proje LAZIS'te" in out
    assert "- Ahmet (çocukluk arkadaşı), person — meslek: yazılımcı" in out
    assert "Ahmet — meslek" in out and "Ankara" in out
    assert "E-ahmet" not in out  # database ids never reach the model
    enum = extraction.schema()["properties"]["items"]["items"]["properties"]["predicate"]["enum"]
    assert enum == registry.keys()


def test_parse_accepts_only_the_expected_shape() -> None:
    assert extraction.parse(json.dumps({"items": [item()]})) == [item()]
    assert extraction.parse('{"items": []}') == []
    assert extraction.parse("bu JSON değil") is None
    assert extraction.parse('{"facts": []}') is None
    assert extraction.parse('["x"]') is None


def test_valid_items_become_candidates() -> None:
    v = extraction.validate([item()], [T1])
    assert v.dropped == {} and len(v.accepted) == 1
    c = v.accepted[0].candidate
    assert (v.accepted[0].message_id, c.predicate, c.value, c.change) == (
        "MSG1",
        "location",
        "İzmir",
        True,
    )
    assert c.quote == "artık İzmir'de yaşıyorum" and c.about == "user" and c.origin == "stated"


def test_quotes_must_come_from_the_target_message() -> None:
    cases = {
        "unknown_message": item(message="m9"),
        # LAZIS's own words, or an earlier message, are not evidence.
        "quote_not_found": item(quote="Ankara'da yaşadığınızı söylemiştiniz"),
        "unknown_predicate": item(predicate="password"),
        "empty": item(value=" "),
    }
    for reason, bad in cases.items():
        assert extraction.validate([bad], [T1]).dropped == {reason: 1}, reason
    # Small differences in case, punctuation and diacritics are tolerated.
    assert extraction.validate([item(quote="ARTIK IZMIRDE YASIYORUM")], [T1]).accepted


def test_entities_must_be_grounded_and_fit_the_predicate() -> None:
    known = [Known(AHMET)]
    q = "Ahmet'le de dün görüştüm"
    met = item(predicate="event", value="görüştük", statement="Kullanıcı Ahmet'le görüştü.",
               entity="Ahmet", relation="arkadaşım", quote=q)  # fmt: skip
    ref = extraction.validate([met], [T1], known).accepted[0].candidate.entity
    # "arkadaşım" is not in the message: the relation is not the user's, so it is dropped.
    assert ref is not None and (ref.name, ref.kind, ref.relation) == ("Ahmet", "person", None)
    assert ref.ref_id is None  # resolution decides, never the model

    ghost = item(predicate="occupation", entity="Mehmet", quote=q)  # not in the message, unknown
    assert extraction.validate([ghost], [T1], known).dropped == {"entity_not_grounded": 1}
    # A known entity is grounded without being named again ("o restoran açmış").
    pronoun = Target("m1", "MSG3", "O da restoran açmış.")
    burak = Entity(
        "E-b", "person", "Burak", "burak", "kuzen", None, None, "active", None, "t", "t", ("Burak",)
    )
    opened = item(entity="Burak", quote="restoran açmış", predicate="event", value="restoran açtı")
    assert extraction.validate([opened], [pronoun], [Known(burak)]).accepted
    # The user named as an entity is the user.
    me = item(entity="Kullanıcı")
    assert extraction.validate([me], [T1]).accepted[0].candidate.about == "user"
    # Project predicates only describe projects; device facts only the user.
    status = item(message="m2", quote="artık FastAPI kullanıyoruz", predicate="project_status")
    assert extraction.validate([status], [T2]).dropped == {"subject_mismatch": 1}
    tech = item(message="m2", quote="artık FastAPI kullanıyoruz", predicate="project_technology",
                entity="LAZIS", value="FastAPI")  # fmt: skip
    assert extraction.validate([tech], [T2]).accepted[0].candidate.entity.kind == "project"  # type: ignore[union-attr]
    laptop = item(predicate="computer", entity="Ahmet", quote=q, value="ThinkPad")
    assert extraction.validate([laptop], [T1], known).dropped == {"subject_mismatch": 1}


def test_untrusted_field_types_are_normalised() -> None:
    odd = item(importance=True, certain="evet", change="true", value="x" * 500, sensitive="gizli")
    c = extraction.validate([odd], [T1]).accepted[0].candidate
    assert c.importance == 0.5 and c.certain and not c.change and c.sensitivity_category is None
    assert len(c.value) == extraction.MAX_VALUE
    assert extraction.validate([item(importance=7)], [T1]).accepted[0].candidate.importance == 1.0


def test_quote_matching() -> None:
    assert extraction.quote_in("İzmir'de yaşıyorum", T1.text)
    assert not extraction.quote_in("Bursa'da yaşıyorum", T1.text)
    assert not extraction.quote_in("Be", T1.text)  # too short to be evidence
    assert text.fold("İZMİR") == "izmir"


def test_prompt_groups_cover_every_predicate_once() -> None:
    # Split on commas outside the parenthesised hints.
    entries = [
        e.strip() for _, keys in extraction.PROMPT_GROUPS for e in re.split(r",(?![^(]*\))", keys)
    ]
    listed = [re.match(r"[a-z_]+", e).group(0) for e in entries]  # type: ignore[union-attr]
    assert sorted(listed) == sorted(registry.keys())
    singles = {k for k, p in registry.PREDICATES.items() if p.cardinality == "single"}
    assert {re.match(r"[a-z_]+", e).group(0) for e in entries if "*" in e} == singles  # type: ignore[union-attr]


def test_a_relation_must_come_from_the_user() -> None:
    known = [Known(AHMET)]
    t = Target("m1", "MSG4", "Ahmet bugün aradı, satranç kulübüne yazılmış.")
    copied = item(entity="Ahmet", relation="çocukluk arkadaşı", quote="satranç kulübüne yazılmış",
                  predicate="interest", value="satranç")  # fmt: skip
    v = extraction.validate([copied], [t], known)
    assert v.accepted[0].candidate.entity.relation is None  # type: ignore[union-attr]
    assert v.dropped == {"relation_not_grounded": 1}
    answer = Target("m1", "MSG5", "Çocukluk arkadaşım olan.")
    ok = extraction.validate([dict(copied, quote="Çocukluk arkadaşım olan")], [answer], known)
    assert ok.accepted[0].candidate.entity.relation == "çocukluk arkadaşı"  # type: ignore[union-attr]
    said_before = extraction.validate(
        [copied], [t], known, context=["Çocukluk arkadaşım Ahmet geldi."]
    )
    assert said_before.accepted[0].candidate.entity.relation == "çocukluk arkadaşı"  # type: ignore[union-attr]
