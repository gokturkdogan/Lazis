"""Relationship vocabulary (MEMORY_ARCHITECTURE P7.2): typed, directed or symmetric, with
inverse readings computed at query time — never stored (ADR-0016).

A stored relationship (source, type, target) reads:

* for a **role** type: "target is source's ⟨label⟩" — (Ahmet, sibling, Mehmet) → "Mehmet,
  Ahmet'in kardeşi"; (user, childhood_friend, Ahmet) → "Ahmet, kullanıcının çocukluk arkadaşı";
* for an **affiliation** type: "source ⟨label⟩ target" — (Ahmet, works_at, X) → "Ahmet'in
  çalıştığı yer: X", read backwards as "X'in çalışanı: Ahmet".

Read from the other end, a symmetric type is itself, a directed type has its inverse
(mother → child), and a type without an inverse (``acquaintance``: "Ahmet Mehmet'i tanıyor"
does not mean Mehmet knows Ahmet) has **no** reading from the other end.

``lexicon`` maps the user's words ("çocukluk arkadaşım", "ablası", "patronu") to a type, on
folded text with Turkish possessive and genitive endings tolerated.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from lazis.memory import text

Category = Literal["family", "social", "work", "organization", "project", "place", "event"]
Kind = Literal["person", "project", "organization", "place", "event", "group", "thing"]

PEOPLE: tuple[Kind, ...] = ("person",)
ORGS: tuple[Kind, ...] = ("organization", "group")


@dataclass(frozen=True)
class RelType:
    key: str
    label: str  # role: what the target is to the source · affiliation: what the target is
    inverse_label: str  # what the source is to the target
    category: Category
    symmetric: bool = False
    inverse: str | None = None  # the type read from the target's side (directed role types)
    invertible: bool = True  # False: no reading from the target's side at all
    source_kinds: tuple[Kind, ...] = PEOPLE
    target_kinds: tuple[Kind, ...] = PEOPLE
    single: bool = False  # at most one current target per source (spouse, lives_in)
    exclusive: str | None = None  # types in one group exclude each other for the same pair
    sensitivity: Literal["normal", "personal", "sensitive"] = "personal"
    sensitivity_category: str | None = None
    words: tuple[str, ...] = field(default_factory=tuple)  # the user's words (base forms)


_KIN = "kin"
_R = RelType
TYPES: dict[str, RelType] = {
    t.key: t
    for t in (
        # ----- family (between people; kinship types exclude each other for one pair)
        _R("mother", "annesi", "çocuğu", "family", inverse="child", single=True, exclusive=_KIN,
           words=("anne", "annecik", "valide")),
        _R("father", "babası", "çocuğu", "family", inverse="child", single=True, exclusive=_KIN,
           words=("baba", "peder")),
        _R("parent", "ebeveyni", "çocuğu", "family", inverse="child", exclusive=_KIN),
        _R("child", "çocuğu", "ebeveyni", "family", inverse="parent", exclusive=_KIN,
           words=("cocuk", "cocug", "ogul", "ogl", "kiz", "kiz evlat")),
        _R("sibling", "kardeşi", "kardeşi", "family", symmetric=True, exclusive=_KIN,
           words=("kardes", "kiz kardes", "erkek kardes", "abi", "agabey", "abla")),
        _R("spouse", "eşi", "eşi", "family", symmetric=True, single=True, exclusive=_KIN,
           words=("es", "kari", "koca", "hanim", "zevce")),
        _R("ex_spouse", "eski eşi", "eski eşi", "family", symmetric=True, exclusive=_KIN,
           words=("eski es", "eski kari", "eski koca")),
        _R("partner", "sevgilisi", "sevgilisi", "family", symmetric=True, single=True,
           sensitivity="sensitive", sensitivity_category="intimate",
           words=("sevgili", "partner", "kiz arkadas", "erkek arkadas")),
        _R("ex_partner", "eski sevgilisi", "eski sevgilisi", "family", symmetric=True,
           sensitivity="sensitive", sensitivity_category="intimate",
           words=("eski sevgili", "eski partner")),
        _R("grandmother", "büyükannesi", "torunu", "family", inverse="grandchild", exclusive=_KIN,
           words=("buyukanne", "anneanne", "babaanne", "nine")),
        _R("grandfather", "büyükbabası", "torunu", "family", inverse="grandchild", exclusive=_KIN,
           words=("buyukbaba", "dede")),
        _R("grandparent", "büyük ebeveyni", "torunu", "family", inverse="grandchild",
           exclusive=_KIN),
        _R("grandchild", "torunu", "büyük ebeveyni", "family", inverse="grandparent",
           exclusive=_KIN, words=("torun",)),
        _R("aunt_maternal", "teyzesi", "yeğeni", "family", inverse="niece_nephew", exclusive=_KIN,
           words=("teyze",)),
        _R("aunt_paternal", "halası", "yeğeni", "family", inverse="niece_nephew", exclusive=_KIN,
           words=("hala",)),
        _R("uncle_maternal", "dayısı", "yeğeni", "family", inverse="niece_nephew", exclusive=_KIN,
           words=("dayi",)),
        _R("uncle_paternal", "amcası", "yeğeni", "family", inverse="niece_nephew", exclusive=_KIN,
           words=("amca",)),
        _R("parent_sibling", "amcası/dayısı/halası/teyzesi", "yeğeni", "family",
           inverse="niece_nephew", exclusive=_KIN),
        _R("niece_nephew", "yeğeni", "amcası/dayısı/halası/teyzesi", "family",
           inverse="parent_sibling", exclusive=_KIN, words=("yegen",)),
        _R("cousin", "kuzeni", "kuzeni", "family", symmetric=True, exclusive=_KIN,
           words=("kuzen",)),
        # ----- social
        _R("friend", "arkadaşı", "arkadaşı", "social", symmetric=True,
           words=("arkadas", "dost")),
        _R("childhood_friend", "çocukluk arkadaşı", "çocukluk arkadaşı", "social", symmetric=True,
           words=("cocukluk arkadas",)),
        _R("close_friend", "yakın arkadaşı", "yakın arkadaşı", "social", symmetric=True,
           words=("yakin arkadas", "en yakin arkadas", "can dost")),
        _R("acquaintance", "tanıdığı", "", "social", invertible=False,
           words=("tanidik", "tanidig")),
        _R("neighbor", "komşusu", "komşusu", "social", symmetric=True, words=("komsu",)),
        _R("teacher", "öğretmeni", "öğrencisi", "social", inverse="student",
           words=("ogretmen", "hoca")),
        _R("student", "öğrencisi", "öğretmeni", "social", inverse="teacher",
           words=("ogrenci",)),
        # ----- work (between people)
        _R("colleague", "iş arkadaşı", "iş arkadaşı", "work", symmetric=True,
           words=("is arkadas", "meslektas", "calisma arkadas")),
        _R("business_partner", "iş ortağı", "iş ortağı", "work", symmetric=True,
           words=("is ortag", "is ortak", "ortag", "ortak")),
        _R("employee", "çalışanı", "işvereni", "work", inverse="employer",
           words=("calisan", "eleman")),
        _R("employer", "işvereni", "çalışanı", "work", inverse="employee",
           words=("isveren", "patron")),
        _R("manager", "yöneticisi", "ekibindeki çalışanı", "work", inverse="report",
           words=("yonetici", "mudur", "amir", "sef")),
        _R("report", "ekibindeki çalışanı", "yöneticisi", "work", inverse="manager"),
        _R("client", "müşterisi", "hizmet sağlayıcısı", "work", inverse="service_provider",
           words=("musteri",)),
        _R("service_provider", "hizmet sağlayıcısı", "müşterisi", "work", inverse="client"),
        _R("advisor", "danışmanı", "danışanı", "work", inverse="advisee", words=("danisman",)),
        _R("advisee", "danışanı", "danışmanı", "work", inverse="advisor", words=("danisan",)),
        # ----- organizations and projects (person or group → organization or project)
        _R("works_at", "çalıştığı yer", "çalışanı", "organization", target_kinds=ORGS),
        _R("owns", "sahibi olduğu yer", "sahibi", "organization",
           target_kinds=(*ORGS, "project")),
        _R("founded", "kurduğu yer", "kurucusu", "organization", target_kinds=(*ORGS, "project")),
        _R("manages", "yönettiği yer", "yöneticisi", "organization",
           target_kinds=(*ORGS, "project")),
        _R("member_of", "üyesi olduğu yer", "üyesi", "organization", target_kinds=ORGS),
        _R("works_on", "çalıştığı proje", "projede çalışan", "project",
           source_kinds=(*PEOPLE, "group", "organization"), target_kinds=("project",)),
        _R("develops", "geliştirdiği proje", "geliştiricisi", "project",
           target_kinds=("project",)),
        _R("contributes_to", "katkı sağladığı proje", "katkı sağlayanı", "project",
           target_kinds=("project",)),
        # ----- places and events
        _R("lives_in", "yaşadığı yer", "orada yaşayan", "place", single=True,
           target_kinds=("place",), sensitivity="personal"),
        _R("works_in_place", "çalıştığı şehir", "orada çalışan", "place", target_kinds=("place",)),
        _R("located_in", "bulunduğu yer", "oradaki", "place", single=True,
           source_kinds=("organization", "group", "place", "event", "project"),
           target_kinds=("place",), sensitivity="normal"),
        _R("attended", "katıldığı etkinlik", "katılımcısı", "event", target_kinds=("event",)),
        _R("organized", "düzenlediği etkinlik", "düzenleyeni", "event", target_kinds=("event",)),
        _R("involved_in", "yer aldığı olay", "içinde yer alan", "event", target_kinds=("event",)),
    )
}  # fmt: skip

KEYS = tuple(TYPES)
# Which stored types answer a question asking for the "friend" family, etc.
FAMILIES: dict[str, tuple[str, ...]] = {
    "friend": ("friend", "childhood_friend", "close_friend"),
    "parent": ("mother", "father", "parent"),
    "grandparent": ("grandmother", "grandfather", "grandparent"),
    "parent_sibling": ("aunt_maternal", "aunt_paternal", "uncle_maternal", "uncle_paternal",
                       "parent_sibling"),
}  # fmt: skip


def get(key: str) -> RelType | None:
    return TYPES.get(key)


def answers(key: str) -> tuple[str, ...]:
    """The stored or read types that satisfy a request for ``key`` ("arkadaşı" also finds a
    childhood friend)."""
    return FAMILIES.get(key, (key,))


@dataclass(frozen=True)
class Reading:
    """A relationship as seen from one end: ``other`` is ``this``'s ⟨type⟩."""

    type: str
    forward: bool  # True: read as stored; False: read from the target's side


def reading_from_target(key: str) -> str | None:
    """The type that describes the source when the relationship is read from its target."""
    t = TYPES.get(key)
    if t is None or not t.invertible:
        return None
    if t.symmetric:
        return key
    return t.inverse  # None for affiliations: they have an inverse label, not a type


def kinds_ok(t: RelType, source_kind: str, target_kind: str) -> bool:
    return source_kind in t.source_kinds and target_kind in t.target_kinds


# ----- the user's words -------------------------------------------------------------------
# Possessive (+ genitive) endings after folding (ı→i, ü→u, ö→o): "arkadaşım", "arkadaşımın",
# "kardeşi", "kardeşinin", "annesi", "annesinin", "ablaları".
# No dative/locative endings: they collide with ordinary words ("eşya" = eş + ya).
_SUFFIX = (
    r"(?:ler|lar)?"  # plural
    r"(?:s?i|s?u|y?im|y?um|imiz|umuz|iniz|unuz|m|miz|muz|n|niz|nuz)?"  # possessive
    r"(?:n?in|n?un|y?la|y?le)?"  # genitive / "ile"
)


def _word_pattern(base: str) -> re.Pattern[str]:
    parts = base.split()
    head = r"\s+".join(re.escape(p) for p in parts[:-1])
    last = re.escape(parts[-1]) + _SUFFIX
    return re.compile(rf"^{head + r'\s+' if head else ''}{last}$")


# Longest first: "eski es" before "es", "cocukluk arkadas" before "arkadas".
_LEXICON: list[tuple[str, str, re.Pattern[str]]] = sorted(
    ((t.key, w, _word_pattern(w)) for t in TYPES.values() for w in t.words),
    key=lambda x: -len(x[1]),
)


def lexicon(phrase: str) -> str | None:
    """The type for a relation phrase as the user said it ("çocukluk arkadaşım" →
    ``childhood_friend``, "ablası" → ``sibling``), or None. The whole phrase must match."""
    folded = " ".join(text.words(phrase))
    folded = re.sub(r"^(benim|onun|bizim)\s+", "", folded)
    for key, _w, pattern in _LEXICON:
        if pattern.match(folded):
            return key
    return None


def says_mine(evidence: str | None, key: str) -> bool:
    """Whether the user's words say this relation is theirs, in the first person
    ("kuzenim Selim", "çocukluk arkadaşım", "annemin") — not "Selim'in oğlu"."""
    if not evidence:
        return False
    words = text.words(evidence)
    for i in range(len(words)):
        m = match_at(words, i)
        if m is not None and m[0] == key and first_person(m[2]):
            return True
    return False


# Verbs that state a relationship without its noun ("evlendiler", "boşandılar", "tanıyor",
# "birlikte çalıştık"), as folded stems.
_CUES: dict[str, tuple[str, ...]] = {
    "spouse": ("evli", "evlen", "nikah"),
    "ex_spouse": ("bosan",),
    "partner": ("cikiyor", "cikiyoruz"),
    "colleague": ("calis",),
    "employee": ("calis",),
    "employer": ("calis",),
    "acquaintance": ("tani",),
    "teacher": ("ogret", "ders"),
    "student": ("ogret", "ders"),
}


def named_in(message: str, key: str) -> bool:
    """Whether the user's words name this type (or one it answers for), by its noun or by a
    verb that states it ("evlendi" → spouse)."""
    words = text.words(message)
    cues = _CUES.get(key, ())
    if cues and any(w.startswith(cues) for w in words):
        return True
    for i in range(len(words)):
        m = match_at(words, i)
        if m is not None and (m[0] in answers(key) or key in answers(m[0])):
            return True
    return False


def only_mine(message: str, key: str) -> bool:
    """The message names this type only in the first person ("ablam", never "ablası")."""
    words = text.words(message)
    persons = [
        first_person(m[2])
        for i in range(len(words))
        if (m := match_at(words, i)) is not None and (m[0] in answers(key) or key in answers(m[0]))
    ]
    return bool(persons) and all(persons)


def sensitive_label(phrase: str | None) -> str | None:
    """The sensitivity category when relation words name a sensitive type ("sevgilim" →
    "intimate"), else None."""
    key = lexicon(phrase) if phrase else None
    t = TYPES.get(key) if key else None
    return t.sensitivity_category if t is not None and t.sensitivity == "sensitive" else None


def match_at(words: Sequence[str], i: int) -> tuple[str, int, str] | None:
    """A relation noun starting at ``words[i]`` (one or two words), as (type, words used,
    ending): "kardesimin" → ("sibling", 1, "imin")."""
    for key, w, pattern in _LEXICON:
        n = len(w.split())
        if i + n <= len(words) and pattern.match(" ".join(words[i : i + n])):
            return key, n, words[i + n - 1][len(w.split()[-1]) :]
    return None


# Copula and case endings after a relation noun's own ("kuzeniydi", "kardeşidir",
# "kuzenine", "kardeşiyle"): read only by the reply checks (Phase 10A), never by learning —
# with them, ordinary words would be read as relations there.
_LOOSE_TAIL = re.compile(
    r"(?:y?di|y?du|y?dir|y?dur|y?tir|y?tur|y?mis|y?mus|yken|nde|nda|nden|ndan|ne|na|yle|yla"
    r"|ydiniz|ydunuz|ymis|dir|dur)$"
)


def types_in(words: Sequence[str]) -> list[tuple[str, str]]:
    """(type, possessive ending) for each relation noun in the words, also with a copula or
    case ending (see above)."""
    found: list[tuple[str, str]] = []
    for i, w in enumerate(words):
        m = match_at(words, i)
        if m is None and (tail := _LOOSE_TAIL.search(w)) is not None and tail.start() >= 3:
            m = match_at([w[: tail.start()]], 0)
        if m is not None:
            found.append((m[0], m[2]))
    return found


def second_person(ending: str) -> bool:
    """ "kuzeniniz", "arkadaşınız", "komşunuzun": the user's relation, said to the user."""
    e = re.sub(r"^(?:ler|lar)", "", ending)  # folded: "ınız" is "iniz"
    return e.startswith(("iniz", "unuz", "niz", "nuz"))


def first_person(ending: str) -> bool:
    """True if a relation noun's ending is first-person possessive ("arkadaşım",
    "kardeşimin", "annem", "ablamız"), so the relation is the user's."""
    e = re.sub(r"^(?:ler|lar)", "", ending)
    return bool(re.match(r"^(?:y?im|y?um|m)", e))


# ----- Turkish rendering ------------------------------------------------------------------
_BACK = set("aıou")
_FRONT = set("eiöü")
_VOWELS = _BACK | _FRONT
_HARD = set("fstkçşhp")


def _last_vowel(word: str) -> str:
    for ch in reversed(text.casefold(word)):
        if ch in _VOWELS:
            return ch
    return "e"


def genitive(name: str) -> str:
    """ "Ahmet'in", "Ayşe'nin", "Murat'ın", "Pusula'nın", "Ülkü'nün"."""
    if name == "Kullanıcı":
        return "kullanıcının"
    v = _last_vowel(name)
    suffix = {
        "a": "ın",
        "ı": "ın",
        "o": "un",
        "u": "un",
        "e": "in",
        "i": "in",
        "ö": "ün",
        "ü": "ün",
    }[v]
    ends_vowel = text.casefold(name)[-1:] in _VOWELS
    return f"{name}'{'n' if ends_vowel else ''}{suffix}"


def genitive_of_noun(noun: str) -> str:
    """A possessed noun in the genitive: "kardeşi" → "kardeşinin", "çalıştığı yer" →
    "çalıştığı yerin", "çocukluk arkadaşı" → "çocukluk arkadaşının"."""
    suffix = {"a": "ın", "ı": "ın", "o": "un", "u": "un", "e": "in", "i": "in", "ö": "ün",
              "ü": "ün"}[_last_vowel(noun)]  # fmt: skip
    return f"{noun}{'n' if text.casefold(noun)[-1:] in _VOWELS else ''}{suffix}"


def locative(name: str) -> str:
    """ "Pusula'da", "Ankara'da", "Kervan'da", "Örnek A.Ş.'de"."""
    v = _last_vowel(name)
    vowel = "a" if v in _BACK else "e"
    hard = text.casefold(name)[-1:] in _HARD
    return f"{name}'{'t' if hard else 'd'}{vowel}"


_FOUR = {"a": "ı", "ı": "ı", "o": "u", "u": "u", "e": "i", "i": "i", "ö": "ü", "ü": "ü"}


def reinflect(name: str, suffix: str) -> str:
    """The case suffix another name had, made to fit ``name``: ("Eskişehir", "da") → "de",
    ("Atlas", "dan") → "tan", ("Ankara", "ın") → "nın", ("İzmir", "ya") → "a". Vowel harmony,
    d/t after a hard consonant and the buffer letter after a vowel; "ki" never changes."""
    s = text.casefold(suffix)
    if not s or not s.isalpha():
        return suffix
    body = s[1:] if s[0] in "ny" and len(s) > 1 and s[1] in _VOWELS else s
    genitive = s[0] == "n" and body != s
    tail = "ki" if body.endswith("ki") else ""
    body = body[: len(body) - len(tail)]
    ends_vowel = text.casefold(name)[-1:] in _VOWELS
    hard = text.casefold(name)[-1:] in _HARD
    out, last = "", _last_vowel(name)
    for i, ch in enumerate(body):
        if ch in "ae":
            ch = "a" if last in _BACK else "e"
        elif ch in "ıiuü":
            ch = _FOUR[last]
        elif i == 0 and ch in "dt":
            ch = "t" if hard else "d"
        if ch in _VOWELS:
            last = ch
        out += ch
    if ends_vowel and out[:1] in _VOWELS:
        genitive = genitive or (len(out) == 2 and out[1] == "n")
        out = ("n" if genitive else "y") + out
    return out + tail


def describe(source_name: str, key: str, target_name: str, *, forward: bool = True) -> str:
    """One Turkish line for a reading: "Mehmet: Ahmet'in kardeşi" (forward) or, read from the
    target, "Ahmet: Mehmet'in kardeşi"."""
    t = TYPES[key]
    if forward:
        return f"{target_name}: {genitive(source_name)} {t.label}"
    return f"{source_name}: {genitive(target_name)} {t.inverse_label}"


def describe_for_prompt() -> str:
    """The relationship types for the extraction instruction (key — label)."""
    groups: dict[str, list[str]] = {}
    for t in TYPES.values():
        if t.key in ("parent_sibling", "report", "service_provider", "grandparent", "parent"):
            continue  # reading-only or generic: the model uses the specific types
        groups.setdefault(t.category, []).append(f"{t.key} ({t.label})")
    names = {
        "family": "Aile",
        "social": "Sosyal",
        "work": "İş (kişiler arası)",
        "organization": "Kurum",
        "project": "Proje",
        "place": "Yer",
        "event": "Olay",
    }
    return "\n".join(f"- {names[c]}: {', '.join(v)}" for c, v in groups.items())
