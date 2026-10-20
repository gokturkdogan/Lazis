"""Identity resolution: 150+ distinct scenarios (ADR-0016 §6, brief §7 and §21.2).

Each scenario sets up stored people (names, aliases, the user's relation words), open
"which one?" questions, distinctions, merges or splits; then probes one statement — a fact
about someone, or a relationship whose source, target or both ends must be resolved — and
checks where it lands:

* an index → attached to that stored entity;
* ``new`` → a new entity was created for that end;
* ``ask`` → nothing written, the user is asked;
* ``user`` → the user;
* ``drop`` → refused (kind mismatch).

The scenarios differ in structure, not just in names. Synthetic data only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from lazis.ids import utc_now_iso
from lazis.memory import graphstore as gs
from lazis.memory import relationships as rels
from lazis.memory import repository as repo
from lazis.memory import service
from lazis.memory.models import USER_ID, Candidate, EntityRef, RelCandidate
from lazis.memory.service import Source
from lazis.storage import StorageHandle, driver

SRC = Source("message", "msg-id-1", "conv-id")
PROBE_TYPE = "client"  # a type no relation word maps to (keeps the user edges apart)


@dataclass(frozen=True)
class S:
    id: str
    setup: tuple[tuple[Any, ...], ...]
    probe: tuple[Any, ...]
    expect: Any
    note: str = ""


def p(
    name: str, relation: str | None = None, *aliases: str, kind: str = "person"
) -> tuple[Any, ...]:
    return ("p", name, relation, aliases, kind)


CHILDHOOD = p("Ahmet", "çocukluk arkadaşı")
PARTNER = p("Ahmet", "iş ortağı")
COUSIN = p("Ahmet", "kuzen")
TWO = (CHILDHOOD, PARTNER)
THREE = (CHILDHOOD, PARTNER, COUSIN)
MEHMETS = (p("Mehmet", "kardeşi"), p("Mehmet", "komşu"))

SCENARIOS: list[S] = [
    # ----- A. one stored person -----------------------------------------------------------
    S("A01", (CHILDHOOD,), ("fact", "Ahmet", None), 0, "name only, single candidate"),
    S(
        "A02",
        (CHILDHOOD,),
        ("fact", "Ahmet", "arkadaşım"),
        0,
        "relation is a part of the stored one",
    ),
    S("A03", (CHILDHOOD,), ("fact", "Ahmet", "çocukluk arkadaşım"), 0, "same relation, possessive"),
    S(
        "A04",
        (CHILDHOOD,),
        ("fact", "Ahmet", "iş ortağım"),
        "ask",
        "relation contradicts: maybe another Ahmet",
    ),
    S("A05", (CHILDHOOD,), ("fact", "Ahmet'e", None), 0, "dative suffix on the name"),
    S("A06", (CHILDHOOD,), ("fact", "AHMET", None), 0, "upper case"),
    S("A07", (CHILDHOOD,), ("fact", "ahmet", None), 0, "lower case"),
    S("A08", (CHILDHOOD,), ("fact", "Mehmet", None), "new", "another name"),
    S("A09", (CHILDHOOD,), ("src", "Ahmet", None), 0, "relationship source, name only"),
    S("A10", (CHILDHOOD,), ("tgt", "Ahmet", None), 0, "relationship target, name only"),
    S("A11", (CHILDHOOD,), ("src", "Ahmet", "kuzenim"), "ask", "source relation contradicts"),
    S("A12", (CHILDHOOD,), ("tgt", "Ahmet", "kuzenim"), "ask", "target relation contradicts"),
    S(
        "A13",
        (CHILDHOOD,),
        ("fact", "Ahmet Yılmaz", None),
        "new",
        "a full name is a different key: never guessed",
    ),
    S("A14", (CHILDHOOD,), ("fact", "Ahmed", None), "new", "spelling variant: no fuzzy identity"),
    S(
        "A15",
        (CHILDHOOD,),
        ("fact", "Ahmet'in", "çocukluk arkadaşımın"),
        0,
        "genitive name and relation",
    ),
    S(
        "A16",
        (CHILDHOOD,),
        ("fact", "Ahmetle", None),
        "new",
        "an unseparated suffix is not stripped from a name key",
    ),
    S(
        "A17",
        (CHILDHOOD,),
        ("src", "Ahmet", "eski çocukluk arkadaşım"),
        0,
        "an extra word around the same relation",
    ),
    S("A18", (CHILDHOOD,), ("tgt", "Ahmet", "arkadaşım"), 0, "target with a broader relation"),
    # ----- B. stored person without a relation label --------------------------------------
    S("B01", (p("Zeynep"),), ("fact", "Zeynep", None), 0),
    S("B02", (p("Zeynep"),), ("fact", "Zeynep", "komşum"), 0, "no stored relation: compatible"),
    S("B03", (p("Zeynep"),), ("src", "Zeynep", "kardeşim"), 0),
    S("B04", (p("Zeynep"),), ("tgt", "Zeynep", "eşim"), 0),
    S("B05", (p("Zeynep"), p("Ece")), ("fact", "Ece", None), 1, "two different names"),
    S("B06", (p("Zeynep"), p("Ece")), ("tgt", "Zeynep", None), 0),
    # ----- C. two namesakes ---------------------------------------------------------------
    S("C01", TWO, ("fact", "Ahmet", None), "ask", "name only among two"),
    S("C02", TWO, ("fact", "Ahmet", "çocukluk arkadaşım"), 0),
    S("C03", TWO, ("fact", "Ahmet", "iş ortağım"), 1),
    S("C04", TWO, ("fact", "Ahmet", "arkadaşım"), 0, "only the childhood friend fits 'arkadaş'"),
    S("C05", TWO, ("fact", "Ahmet", "kuzenim"), "ask", "neither fits"),
    S("C06", TWO, ("fact", "Ahmet", "ortağım"), 1, "partial relation identifies one"),
    S("C07", TWO, ("src", "Ahmet", None), "ask"),
    S("C08", TWO, ("tgt", "Ahmet", None), "ask"),
    S("C09", TWO, ("src", "Ahmet", "iş ortağım"), 1),
    S("C10", TWO, ("tgt", "Ahmet", "çocukluk arkadaşım"), 0),
    S("C11", TWO, ("fact", "Ahmet'le", None), "ask", "suffix, still ambiguous"),
    S("C12", TWO, ("fact", "Ahmet", "iş ortağımın"), 1, "genitive relation"),
    S("C13", TWO, ("fact", "AHMET", "İŞ ORTAĞIM"), 1, "upper case relation"),
    S("C14", TWO, ("src", "Ahmet", "komşum"), "ask"),
    S("C15", TWO, ("tgt", "Ahmet", "iş ortağı"), 1, "relation without possessive"),
    S(
        "C16",
        (PARTNER, CHILDHOOD),
        ("fact", "Ahmet", "çocukluk arkadaşım"),
        1,
        "storage order does not matter",
    ),
    S("C17", (PARTNER, CHILDHOOD), ("fact", "Ahmet", None), "ask"),
    # ----- D. three namesakes -------------------------------------------------------------
    S("D01", THREE, ("fact", "Ahmet", None), "ask"),
    S("D02", THREE, ("fact", "Ahmet", "kuzenim"), 2),
    S("D03", THREE, ("fact", "Ahmet", "kuzenimin"), 2),
    S("D04", THREE, ("fact", "Ahmet", "iş ortağım"), 1),
    S("D05", THREE, ("fact", "Ahmet", "çocukluk arkadaşım"), 0),
    S("D06", THREE, ("fact", "Ahmet", "arkadaşım"), 0),
    S("D07", THREE, ("fact", "Ahmet", "komşum"), "ask"),
    S("D08", THREE, ("src", "Ahmet", None), "ask"),
    S("D09", THREE, ("tgt", "Ahmet", "kuzenim"), 2),
    S("D10", THREE, ("src", "Ahmet", "ortağım"), 1),
    S("D11", THREE, ("tgt", "Ahmet", None), "ask"),
    S(
        "D12",
        (*THREE, p("Mehmet")),
        ("fact", "Mehmet", None),
        3,
        "an unrelated single name among namesakes",
    ),
    # ----- E. same surname, different people ----------------------------------------------
    S(
        "E01",
        (p("Ahmet Yılmaz", "kuzen"), p("Mehmet Yılmaz", "iş arkadaşı")),
        ("fact", "Ahmet Yılmaz", None),
        0,
    ),
    S(
        "E02",
        (p("Ahmet Yılmaz", "kuzen"), p("Mehmet Yılmaz", "iş arkadaşı")),
        ("fact", "Mehmet Yılmaz", None),
        1,
    ),
    S(
        "E03",
        (p("Ahmet Yılmaz", "kuzen"), p("Mehmet Yılmaz", "iş arkadaşı")),
        ("fact", "Ayşe Yılmaz", None),
        "new",
    ),
    S(
        "E04",
        (p("Ahmet Yılmaz", "kuzen"), p("Mehmet Yılmaz", "iş arkadaşı")),
        ("fact", "ahmet yilmaz", None),
        0,
    ),
    S(
        "E05",
        (p("Ahmet Yılmaz", "kuzen"), p("Mehmet Yılmaz", "iş arkadaşı")),
        ("src", "Mehmet Yılmaz", "iş arkadaşım"),
        1,
    ),
    S(
        "E06",
        (p("Ahmet Yılmaz", "kuzen"), p("Ahmet Kaya", "komşu")),
        ("fact", "Ahmet Kaya", None),
        1,
        "same given name",
    ),
    S(
        "E07",
        (p("Ahmet Yılmaz", "kuzen"), p("Ahmet Kaya", "komşu")),
        ("fact", "Ahmet Yılmaz'ın", None),
        0,
    ),
    S(
        "E08",
        (p("Ahmet Yılmaz", "kuzen"), p("Ahmet Kaya", "komşu")),
        ("tgt", "Ahmet Kaya", "komşum"),
        1,
    ),
    S(
        "E09",
        (p("Ahmet Yılmaz", "kuzen"), p("Ahmet Kaya", "komşu")),
        ("fact", "Yılmaz", None),
        "new",
        "surname alone is not a person key",
    ),
    S(
        "E10",
        (p("Ali Demir"), p("Ali Demirci")),
        ("fact", "Ali Demir", None),
        0,
        "a prefix of another surname",
    ),
    S("E11", (p("Ali Demir"), p("Ali Demirci")), ("fact", "Ali Demirci", None), 1),
    # ----- F. aliases and nicknames -------------------------------------------------------
    S("F01", (p("Mehmet", None, "Memo"),), ("fact", "Memo", None), 0),
    S("F02", (p("Mehmet", None, "Memo"),), ("fact", "Memo'ya", None), 0),
    S("F03", (p("Mehmet", None, "Memo"),), ("fact", "Mehmet", None), 0),
    S("F04", (p("Mehmet", None, "Memo"),), ("src", "Memo", None), 0),
    S("F05", (p("Mehmet", None, "Memo"), p("Elif", None, "Elo")), ("fact", "Elo", None), 1),
    S("F06", (p("Mehmet", None, "Memo"), p("Elif", None, "Elo")), ("fact", "Elif", None), 1),
    S(
        "F07",
        (p("Mehmet", None, "Memo"), p("Memduh", None, "Memo")),
        ("fact", "Memo", None),
        "ask",
        "a shared nickname",
    ),
    S("F08", (p("Mehmet", None, "Memo"), p("Memduh", None, "Memo")), ("fact", "Memduh", None), 1),
    S(
        "F09",
        (p("Mehmet", "kardeşi", "Memo"), p("Memduh", "komşu", "Memo")),
        ("fact", "Memo", "komşum"),
        1,
        "shared nickname, relation decides",
    ),
    S(
        "F10",
        (p("Ayşe Nur", None, "Nur"),),
        ("fact", "Nur", None),
        0,
        "short form registered as alias",
    ),
    S(
        "F11",
        (p("Ayşe Nur", None, "Nur"),),
        ("fact", "Ayşe", None),
        "new",
        "an unregistered short form is not guessed",
    ),
    S("F12", (p("Kemal Bey", None, "Kemal"),), ("tgt", "Kemal", None), 0),
    # ----- G. Turkish letters and case -----------------------------------------------------
    S("G01", (p("Şükrü", "komşu"),), ("fact", "Sukru", None), 0, "typed without diacritics"),
    S("G02", (p("Şükrü", "komşu"),), ("fact", "ŞÜKRÜ", None), 0),
    S("G03", (p("Işıl"),), ("fact", "Isil", None), 0),
    S("G04", (p("Işıl"),), ("fact", "IŞIL", None), 0, "dotless capital I"),
    S("G05", (p("İsmail"),), ("fact", "ismail", None), 0),
    S("G06", (p("İsmail"),), ("fact", "İSMAİL", None), 0, "dotted capital İ"),
    S("G07", (p("Gül"),), ("fact", "Gul", None), 0),
    S("G08", (p("Çağrı"),), ("fact", "Cagri", None), 0),
    S("G09", (p("Çağrı"),), ("fact", "Çağrı'nın", None), 0),
    S("G10", (p("Öznur"),), ("tgt", "Oznur", None), 0),
    S("G11", (p("Ilgaz"), p("Ilgın")), ("fact", "ılgaz", None), 0, "lower dotless ı"),
    S(
        "G12",
        (p("Şule"), p("Sule")),
        ("fact", "Sule", None),
        "ask",
        "two records whose folded names collide",
    ),
    # ----- H. missing relation info and open questions ------------------------------------
    S(
        "H01",
        (CHILDHOOD, ("q", "Ahmet")),
        ("fact", "Ahmet", None),
        "ask",
        "an open 'which Ahmet?' blocks guessing",
    ),
    S(
        "H02",
        (CHILDHOOD, ("q", "Ahmet")),
        ("fact", "Ahmet", "çocukluk arkadaşım"),
        0,
        "the user's relation words decide",
    ),
    S(
        "H03",
        (CHILDHOOD, ("q", "Mehmet")),
        ("fact", "Ahmet", None),
        0,
        "a question about another name does not block",
    ),
    S("H04", (CHILDHOOD, ("q", "Ahmet")), ("src", "Ahmet", None), "ask"),
    S("H05", (CHILDHOOD, ("q", "Ahmet")), ("tgt", "Ahmet", None), "ask"),
    S("H06", (CHILDHOOD, ("q", "Ahmet")), ("tgt", "Ahmet", "arkadaşım"), 0),
    S("H07", (p("Zeynep"), ("q", "Zeynep")), ("fact", "Zeynep", None), "ask"),
    S(
        "H08",
        (p("Zeynep"), ("q", "Zeynep")),
        ("fact", "Zeynep", "komşum"),
        0,
        "relation given: no stored relation to contradict",
    ),
    S(
        "H09",
        (("q", "Ahmet"),),
        ("fact", "Ahmet", None),
        "new",
        "an open question but no stored Ahmet: nothing to confuse",
    ),
    # ----- I. distinctions and splits -----------------------------------------------------
    S(
        "I01",
        (CHILDHOOD, ("split", 0, "Ahmet", "kuzen")),
        ("fact", "Ahmet", None),
        "ask",
        "after a split there are two",
    ),
    S("I02", (CHILDHOOD, ("split", 0, "Ahmet", "kuzen")), ("fact", "Ahmet", "kuzenim"), 1),
    S(
        "I03",
        (CHILDHOOD, ("split", 0, "Ahmet", "kuzen")),
        ("src", "Ahmet", "çocukluk arkadaşım"),
        0,
    ),
    S("I04", (CHILDHOOD, ("split", 0, "Ahmet", "kuzen")), ("tgt", "Ahmet", None), "ask"),
    S(
        "I05",
        (CHILDHOOD, ("split", 0, "Ahmet", None)),
        ("fact", "Ahmet", "çocukluk arkadaşım"),
        0,
        "the split-off record has no relation",
    ),
    S(
        "I06",
        (TWO, ("d", 0, 1)),
        ("fact", "Ahmet", "iş ortağım"),
        1,
        "distinct pair, relation decides",
    ),
    S("I07", (TWO, ("d", 0, 1)), ("fact", "Ahmet", None), "ask"),
    S(
        "I08",
        (p("Can"), p("Can"), ("d", 0, 1)),
        ("fact", "Can", None),
        "ask",
        "two unlabelled namesakes",
    ),
    S(
        "I09",
        (p("Can"), p("Can"), ("d", 0, 1)),
        ("fact", "Can", "komşum"),
        "ask",
        "a relation neither has stored still fits both",
    ),
    # ----- J. after a merge -----------------------------------------------------------------
    S(
        "J01",
        (CHILDHOOD, p("Ahmet Kaya"), ("m", 0, 1)),
        ("fact", "Ahmet Kaya", None),
        0,
        "the merged name is an alias now",
    ),
    S(
        "J02",
        (CHILDHOOD, p("Ahmet Kaya"), ("m", 0, 1)),
        ("fact", "Ahmet", None),
        0,
        "one active record left",
    ),
    S(
        "J03",
        (CHILDHOOD, p("Ahmet Kaya"), ("m", 0, 1)),
        ("src", "Ahmet Kaya", "çocukluk arkadaşım"),
        0,
    ),
    S(
        "J04",
        (CHILDHOOD, p("Ahmet", "kuzen"), ("m", 0, 1)),
        ("fact", "Ahmet", None),
        0,
        "namesakes merged by the user",
    ),
    S(
        "J05",
        (CHILDHOOD, p("Ahmet", "kuzen"), ("m", 0, 1)),
        ("fact", "Ahmet", "kuzenim"),
        "ask",
        "the survivor kept its own relation label",
    ),
    S("J06", (p("Mehmet", None, "Memo"), p("Mehmet Can"), ("m", 0, 1)), ("tgt", "Memo", None), 0),
    S(
        "J07",
        (p("Mehmet", None, "Memo"), p("Mehmet Can"), ("m", 0, 1)),
        ("tgt", "Mehmet Can", None),
        0,
    ),
    # ----- K. kinds ---------------------------------------------------------------------------
    S("K01", (p("Pusula", kind="project"),), ("fact", "Pusula", None, "project"), 0),
    S(
        "K02",
        (p("Pusula", kind="project"),),
        ("fact", "Pusula", None, "person"),
        "new",
        "a person named like a project",
    ),
    S(
        "K03",
        (p("Pusula", kind="project"),),
        ("rel", "works_on", ("Deniz", None, "person"), ("Pusula", None, "project")),
        ("tgt", 0),
    ),
    S(
        "K04",
        (p("Pusula", kind="project"),),
        ("rel", "works_at", ("Deniz", None, "person"), ("Pusula", None, "organization")),
        "drop",
        "a project is not an employer",
    ),
    S(
        "K05",
        (p("Örnek A.Ş.", kind="organization"),),
        ("rel", "works_at", ("Deniz", None, "person"), ("Örnek A.Ş.", None, "organization")),
        ("tgt", 0),
    ),
    S(
        "K06",
        (p("Deniz"),),
        ("rel", "lives_in", ("Ece", None, "person"), ("Deniz", None, "place")),
        "drop",
        "'Deniz' is a stored person, not a place",
    ),
    S(
        "K07",
        (p("Ankara", kind="place"),),
        ("rel", "lives_in", ("Ece", None, "person"), ("Ankara", None, "place")),
        ("tgt", 0),
    ),
    S(
        "K08",
        (p("Ankara", kind="place"),),
        ("rel", "works_at", ("Ece", None, "person"), ("Ankara", None, "organization")),
        "drop",
    ),
    S(
        "K09",
        (p("Ahmet"),),
        ("rel", "works_at", ("Ece", None, "person"), ("Ahmet", None, "person")),
        "drop",
        "a person is not a workplace",
    ),
    S(
        "K10",
        (p("Kervan", kind="group"),),
        ("rel", "member_of", ("Ece", None, "person"), ("Kervan", None, "group")),
        ("tgt", 0),
    ),
    S(
        "K11",
        (p("Mezuniyet", kind="event"),),
        ("rel", "attended", ("Ece", None, "person"), ("Mezuniyet", None, "event")),
        ("tgt", 0),
    ),
    S(
        "K12",
        (),
        ("rel", "attended", ("Ece", None, "person"), ("Mezuniyet", None, "person")),
        "drop",
        "an event must be an event",
    ),
    # ----- L. the user ----------------------------------------------------------------------
    S(
        "L01",
        (),
        ("rel", PROBE_TYPE, ("ben", None, "person"), ("Ahmet", None, "person")),
        ("src", "user"),
    ),
    S(
        "L02",
        (),
        ("rel", PROBE_TYPE, ("Ahmet", None, "person"), ("kendim", None, "person")),
        ("tgt", "user"),
    ),
    S(
        "L03",
        (),
        ("rel", PROBE_TYPE, ("Kullanıcı", None, "person"), ("Ahmet", None, "person")),
        ("src", "user"),
    ),
    S(
        "L04",
        (p("Kullanıcı Bey"),),
        ("fact", "Kullanıcı Bey", None),
        0,
        "a name that only starts like 'Kullanıcı'",
    ),
    S(
        "L05",
        (),
        ("rel", PROBE_TYPE, ("benim", None, "person"), ("ben", None, "person")),
        "drop",
        "user to user",
    ),
    # ----- M. both ends ---------------------------------------------------------------------
    S(
        "M01",
        (*TWO, *MEHMETS),
        ("rel", PROBE_TYPE, ("Ahmet", None, "person"), ("Mehmet", None, "person")),
        "ask",
        "source first",
    ),
    S(
        "M02",
        (*TWO, *MEHMETS),
        ("rel", PROBE_TYPE, ("Ahmet", "çocukluk arkadaşım", "person"), ("Mehmet", None, "person")),
        "ask",
        "then the target",
    ),
    S(
        "M03",
        (*TWO, *MEHMETS),
        (
            "rel",
            PROBE_TYPE,
            ("Ahmet", "çocukluk arkadaşım", "person"),
            ("Mehmet", "komşum", "person"),
        ),
        ("both", 0, 3),
    ),
    S(
        "M04",
        (*TWO, *MEHMETS),
        ("rel", PROBE_TYPE, ("Ahmet", "iş ortağım", "person"), ("Mehmet", "kardeşi", "person")),
        ("both", 1, 2),
    ),
    S(
        "M05",
        (*TWO, p("Mehmet")),
        ("rel", PROBE_TYPE, ("Ahmet", "iş ortağım", "person"), ("Mehmet", None, "person")),
        ("both", 1, 2),
    ),
    S(
        "M06",
        (*TWO, p("Mehmet")),
        ("rel", PROBE_TYPE, ("Ahmet", None, "person"), ("Mehmet", None, "person")),
        "ask",
        "a clear target does not settle the source",
    ),
    S(
        "M07",
        (CHILDHOOD, *MEHMETS),
        ("rel", PROBE_TYPE, ("Ahmet", None, "person"), ("Mehmet", None, "person")),
        "ask",
        "a clear source does not settle the target",
    ),
    S(
        "M08",
        (CHILDHOOD, *MEHMETS),
        ("rel", PROBE_TYPE, ("Ahmet", None, "person"), ("Mehmet", "komşum", "person")),
        ("both", 0, 2),
    ),
    S(
        "M09",
        (CHILDHOOD,),
        ("rel", PROBE_TYPE, ("Ahmet", None, "person"), ("Zehra", None, "person")),
        ("both", 0, "new"),
    ),
    S(
        "M10",
        (),
        ("rel", PROBE_TYPE, ("Ahmet", None, "person"), ("Zehra", None, "person")),
        ("both", "new", "new"),
    ),
    S(
        "M11",
        (CHILDHOOD,),
        ("rel", PROBE_TYPE, ("Ahmet", None, "person"), ("Ahmet", None, "person")),
        "drop",
        "the same person on both ends",
    ),
    S(
        "M12",
        (TWO),
        (
            "rel",
            PROBE_TYPE,
            ("Ahmet", "çocukluk arkadaşım", "person"),
            ("Ahmet", "iş ortağım", "person"),
        ),
        ("both", 0, 1),
        "two namesakes related to each other",
    ),
    S(
        "M13",
        (TWO),
        ("rel", PROBE_TYPE, ("Ahmet", "çocukluk arkadaşım", "person"), ("Ahmet", None, "person")),
        "ask",
    ),
    S(
        "M14",
        (p("Ece", None, "Ecem"), p("Can")),
        ("rel", PROBE_TYPE, ("Ecem", None, "person"), ("Can", None, "person")),
        ("both", 0, 1),
    ),
    S(
        "M15",
        (*THREE, *MEHMETS),
        ("rel", PROBE_TYPE, ("Ahmet", "kuzenim", "person"), ("Mehmet", "kardeşi", "person")),
        ("both", 2, 3),
    ),
]

# ----- N. structured variations: one dimension at a time ------------------------------------
# Relation words in their many Turkish forms must keep landing on the right namesake.
_RELATION_FORMS = [
    ("çocukluk arkadaşım", 0), ("çocukluk arkadaşımın", 0), ("çocukluk arkadaşıyla", 0),
    ("çocukluk arkadaşı", 0), ("iş ortağım", 1), ("iş ortağımın", 1), ("iş ortağıyla", 1),
    ("ortaklarımdan", 1), ("kuzenim", 2), ("kuzenimin", 2), ("kuzeniyle", 2),
    ("kuzenlerim", 2), ("arkadaşım", 0), ("arkadaşlarım", 0), ("komşum", "ask"),
    ("eski komşum", "ask"), ("ablam", "ask"), ("patronum", "ask"),
]  # fmt: skip
for i, (words, exp) in enumerate(_RELATION_FORMS, start=1):
    SCENARIOS.append(
        S(f"N{i:02d}", THREE, ("fact", "Ahmet", words), exp, f"relation form '{words}'")
    )

# Name forms with suffixes against a single stored name and against namesakes.
_NAME_FORMS = ["Ahmet'in", "Ahmet'e", "Ahmet'i", "Ahmet'le", "Ahmet'ten", "Ahmet'teki", "Ahmet’e"]
for i, form in enumerate(_NAME_FORMS, start=1):
    SCENARIOS.append(
        S(f"O{i:02d}", (CHILDHOOD,), ("fact", form, None), 0, f"name form '{form}', single")
    )
    SCENARIOS.append(
        S(f"O{i + 20:02d}", TWO, ("fact", form, None), "ask", f"name form '{form}', namesakes")
    )

# Every relationship end position against every population shape (structural, not names).
_POPULATIONS: list[tuple[str, tuple[tuple[Any, ...], ...], Any, Any]] = [
    ("single", (CHILDHOOD,), 0, "ask"),
    ("two", TWO, "ask", 1),
    ("three", THREE, "ask", 1),
    ("open-question", (CHILDHOOD, ("q", "Ahmet")), "ask", "ask"),
    ("distinct", (*TWO, ("d", 0, 1)), "ask", 1),
]
for i, (name, pop, bare, with_partner) in enumerate(_POPULATIONS, start=1):
    SCENARIOS.append(
        S(f"P{i:02d}s", pop, ("src", "Ahmet", None), bare, f"{name}: source, bare name")
    )
    SCENARIOS.append(
        S(f"P{i:02d}t", pop, ("tgt", "Ahmet", None), bare, f"{name}: target, bare name")
    )
    SCENARIOS.append(
        S(
            f"P{i:02d}r",
            pop,
            ("src", "Ahmet", "iş ortağım"),
            with_partner,
            f"{name}: source with 'iş ortağım'",
        )
    )

assert len({s.id for s in SCENARIOS}) == len(SCENARIOS)


# ----- runner ---------------------------------------------------------------------------------
def _setup(c: driver.Connection, steps: tuple[tuple[Any, ...], ...]) -> list[str]:
    from lazis.storage.unit_of_work import UnitOfWork

    now = utc_now_iso()
    ids: list[str] = []
    flat: list[tuple[Any, ...]] = []
    for st in steps:
        flat.extend(st if st and isinstance(st[0], tuple) else (st,))
    for st in flat:
        if st[0] == "p":
            _, name, relation, aliases, kind = st
            with UnitOfWork(c, kind="import", actor="system", summary="kurulum") as _u:
                e = repo.insert_entity(c, kind=kind, name=name, relation=relation, description=None,
                                       now=now, aliases=aliases)  # fmt: skip
            ids.append(e.id)
        elif st[0] == "q":
            with UnitOfWork(c, kind="import", actor="system", summary="soru") as _u:
                repo.insert_inbox(c, type="ambiguous_entity", summary=f"Hangi {st[1]}?",
                                  payload={"candidate": {"statement": "x", "entity": {"name": st[1]}},
                                           "options": []}, now=now)  # fmt: skip
        elif st[0] == "d":
            with UnitOfWork(c, kind="import", actor="system", summary="ayrım") as _u:
                gs.add_distinction(c, ids[int(st[1])], ids[int(st[2])], now)
        elif st[0] == "m":
            service.merge_entities(c, ids[int(st[1])], ids[int(st[2])])
        elif st[0] == "split":
            new = service.split_entity(c, ids[int(st[1])], [], name=str(st[2]), relation=st[3])
            ids.append(new.id)
    return ids


def _ref(spec: tuple[Any, ...]) -> EntityRef:
    name, relation, kind = spec
    return EntityRef(name, kind, relation)


def _where(eid: str, ids: list[str], created: list[str]) -> Any:
    if eid == USER_ID:
        return "user"
    if eid in ids:
        return ids.index(eid)
    return "new" if eid in created else f"?{eid}"


def _probe(c: driver.Connection, sc: S, ids: list[str]) -> Any:
    kind, *args = sc.probe
    if kind == "fact":
        name, relation = args[0], args[1]
        ekind = args[2] if len(args) > 2 else "person"
        cand = Candidate(predicate="note", value=f"not {sc.id}", statement=f"{name} hakkında not {sc.id}",
                         about="entity", entity=EntityRef(name, ekind, relation))  # fmt: skip
        r = service.apply_candidates(c, [cand], source=SRC, explicit=False)
        if r.inbox:
            return "ask"
        if not r.created:
            return "drop"
        m = repo.get_memory(c, r.created[0])
        assert m is not None and m.subject_id is not None
        return _where(m.subject_id, ids, r.entities_created)
    if kind in ("src", "tgt"):
        name, relation = args
        me, other = EntityRef(name, "person", relation), EntityRef(f"Öteki{sc.id}", "person")
        rc = RelCandidate(type=PROBE_TYPE, source=me if kind == "src" else other,
                          target=other if kind == "src" else me, quote="alıntı")  # fmt: skip
    else:
        type_, s_spec, t_spec = args
        rc = RelCandidate(type=type_, source=_ref(s_spec), target=_ref(t_spec), quote="alıntı")
    r = rels.apply_relations(c, [rc], source=SRC, explicit=False)
    if r.inbox:
        return "ask"
    made = [x for x in (gs.get_relationship(c, i) for i in r.created) if x and x.type == rc.type]
    if not made:
        return "drop"
    e = made[0]
    s_at = _where(e.source_id, ids, r.entities_created)
    t_at = _where(e.target_id, ids, r.entities_created)
    if kind == "src":
        return s_at
    if kind == "tgt":
        return t_at
    exp = sc.expect
    if isinstance(exp, tuple) and exp[0] == "tgt":
        return ("tgt", t_at)
    if isinstance(exp, tuple) and exp[0] == "src":
        return ("src", s_at)
    return ("both", s_at, t_at)


def test_there_are_at_least_150_distinct_scenarios() -> None:
    assert len(SCENARIOS) >= 150
    structures = {(s.setup, s.probe[:1] + tuple(x for x in s.probe[1:] if not isinstance(x, str) or x not in ("Ahmet",)))
                  for s in SCENARIOS}  # fmt: skip
    assert len(structures) >= 140  # not the same scenario with another name


@pytest.mark.parametrize("sc", SCENARIOS, ids=lambda s: s.id)
def test_identity(storage: StorageHandle, sc: S) -> None:
    ids = storage.db.run_sync(lambda c: _setup(c, sc.setup))
    got = storage.db.run_sync(lambda c: _probe(c, sc, ids))
    assert got == sc.expect, f"{sc.id}: {sc.note}"
    # Safety net for every scenario: no two stored entities were merged silently.
    merged = storage.db.run_sync(lambda c: c.execute(
        "SELECT COUNT(*) FROM memory_entities WHERE status = 'merged'").fetchone()[0])  # fmt: skip
    assert merged == sum(1 for st in sc.setup if st and st[0] == "m")
