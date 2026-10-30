"""When something the user says is true: in the past, now, or in the future (Phase 9).

Read from the user's own words around the extracted quote — never from the model's opinion
and never with an invented date:

* **past** — "eskiden", "önceden", "bir zamanlar", "geçen yıl … -yordum", "-mıştım", a past
  form of living / working / studying somewhere ("İstanbul'da yaşadım", "Kervan'da
  çalıştım"): history, not today's fact;
* **future** — "-acağım / -eceğim", "gelecek yıl", "seneye", "yakında": a plan, not a fact;
* **current** — everything else, including a change that happened ("taşındım", "geçtim",
  "artık … -yorum"): it is true now.

A clause is the part of the sentence the quote is in ("Eskiden öğretmendim, artık yazılım
geliştiricisiyim" has two). ``change_marked`` says whether the words say something changed
at all: a model's "it changed" without such words is not trusted (a different city without
"artık" or "taşındı" is a conflict to ask about, not an update).
"""

from __future__ import annotations

import re
from typing import Literal

from lazis.memory import text

Tense = Literal["past", "current", "future"]

# Clauses end at a full stop, or at a comma / "ama" that turns to another time or a contrast
# ("Eskiden öğretmendim, artık …"). A comma inside a list ("İstanbul, Ankara ve İzmir'de
# yaşadım") does not end a clause.
_CLAUSE = re.compile(
    r"[.;!?]+|,\s*(?=(?:ama|fakat|ancak|artık|şimdi|şu an|eskiden|önceden|sonra|oysa|halbuki|"
    r"yine de|bugün|geçen|gelecek|seneye|haftaya|yakında|önümüzdeki|ileride)\b)"
    r"|\s(?:ama|fakat|ancak|oysa|halbuki|ve şimdi|ve artık)\s",
    re.IGNORECASE,
)

_PAST_ADVERB = re.compile(
    r"\b(eskiden|onceden|bir zamanlar|vaktiyle|bir donem|gecmiste|yillarca|cocukken|"
    r"gencken|ogrenciyken|gecen (?:yil|sene|ay|hafta|yaz|kis|bahar|donem)|"
    r"\d+ (?:yil|sene|ay|hafta) once|o zamanlar)\b"
)
# "çalışıyordum", "yaşıyordu", "okuyorduk"; "taşınmıştım"
_PAST_CONTINUOUS = re.compile(r"(?:iyor|uyor|yor)du(?:m|k|n|nuz|niz|lar)?$|m[iu]st[iu](?:m|k|n)?$")
# Simple past of living / working / studying somewhere: history ("İzmir'de yaşadım").
_PAST_STATE_VERB = re.compile(
    r"^(?:yasad|oturd|calist|okud|kald|bulund|gorev yapt|ogretmenlik yapt)[iu](?:m|k|n|nuz|niz)?$"
)
# A change that happened (its result is true now): "taşındı", "geçtim", "başlattım". Leaving
# ("ayrıldım", "bıraktım") is not one: what was left is history ("Eskiden sigara içerdim,
# bıraktım").
_CHANGE_VERB = re.compile(
    r"\b(tasin\w*|gec(?:tim|ti|tik)|basla\w*|degis\w*|emekli ol\w*|"
    r"evlen\w*|bosan\w*|mezun ol\w*|kur(?:dum|du|duk)|actim|acti)\b"
)

_FUTURE = re.compile(r"(?:acag|eceg)(?:im|iz)$|(?:acak|ecek)(?:sin|siniz|lar)?$")
_FUTURE_ADVERB = re.compile(
    r"\b(gelecek (?:yil|sene|ay|hafta|yaz|kis)|seneye|haftaya|yakinda|ileride|"
    r"bir gun|planliyorum|dusunuyorum)\b"
)
_NOT_FUTURE = frozenset({"gelecek"})  # the adjective "gelecek" (next) is handled above

_CHANGE = re.compile(
    r"\b(artik|simdi|su an|su sira|bundan boyle|yeni|yeniden|"
    r"tasin\w*|gec(?:tim|ti|tik|mis\w*|ecegim)|basla\w*|ayril\w*|birak\w*|degis\w*|"
    r"emekli ol\w*|evlen\w*|bosan\w*|mezun ol\w*|terk et\w*|kapat\w*|sat(?:tim|ti)|"
    r"\w+ (?:beri)|aslinda|yanlis (?:soyledim|dedim)|duzeltiyorum|degil|"
    # "Bildiklerini güncelle: 35 yaşındayım" (Phase 9.1): the user says it changed.
    r"guncelle\w*)\b"
)

_TIME_PHRASE = re.compile(
    r"(?<![\w'’])(\w+(?:['’](?:ten|tan|den|dan)) beri|"
    r"(?:19|20)\d\d(?:['’][a-zçğıöşü]+)?|"
    r"(?:gecen|bu|gelecek|onumuzdeki) (?:yil|sene|ay|hafta|yaz|kis|bahar|sonbahar)|"
    r"(?:\d+|bir|iki|uc|dort|bes|alti|yedi|sekiz|dokuz|on|birkac) (?:yil|sene|ay|hafta|gun) "
    r"(?:once|sonra|onceye kadar)|"
    r"(?:dun|bugun|evvelki gun|yarin|seneye|haftaya|gelecek ay)|"
    r"(?:ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik)"
    r"(?:['’][a-zçğıöşü]+)?(?: \d{4})?|"
    r"cocukken|ogrenciyken)"
)


def clauses(message: str) -> list[str]:
    parts = [p.strip() for p in _CLAUSE.split(message)]
    return [p for p in parts if p]


def clause_of(message: str, quote: str | None, anchor: str | None = None) -> str:
    """The clause of ``message`` the quote is in (the quote itself when it is not found).
    ``anchor`` (the value, or the person a relationship is with) picks the clause when the
    quote spans several ("… çalışıyordum, artık Pusula'dayım" → the one with "Pusula")."""
    q = text.fold(quote or "").strip()
    if anchor:
        key = text.name_key(anchor)
        with_anchor = [c for c in clauses(message) if key and key in text.name_key(c)]
        if len(with_anchor) == 1 and (
            not q or any(w in q for w in text.fold(with_anchor[0]).split())
        ):
            return with_anchor[0]
    if not q:
        return message
    for c in clauses(message):
        fc = text.fold(c)
        if q in fc or fc in q:
            return c
    # The quote spans clauses ("Eskiden öğretmendim, artık …"): take the clause it starts in.
    first = " ".join(text.words(quote or "")[:2])
    for c in clauses(message):
        if first and first in " ".join(text.words(c)):
            return c
    return quote or message


def tense(clause: str) -> Tense:
    words = text.words(clause)
    joined = " ".join(words)
    if _FUTURE_ADVERB.search(joined) or any(
        _FUTURE.search(w) for w in words if w not in _NOT_FUTURE
    ):
        return "future"
    past_adverb = bool(_PAST_ADVERB.search(joined))
    if any(_PAST_CONTINUOUS.search(w) for w in words):
        return "past"
    for i in range(len(words)):
        if _PAST_STATE_VERB.match(words[i]) or (
            i + 1 < len(words) and _PAST_STATE_VERB.match(f"{words[i]} {words[i + 1]}")
        ):
            return "past"
    if past_adverb:
        # "Eskiden öğretmendim" is history; "Geçen ay LAZIS'i başlattım" / "2024'te taşındı"
        # is a change that happened then and is true now.
        return "current" if _CHANGE_VERB.search(joined) else "past"
    return "current"


# Leaving something ("Kervan'dan ayrıldım", "işi bıraktım", "istifa ettim"): what was left is
# in the past — unless the clause also arrives somewhere ("Ankara'dan ayrılıp İzmir'e taşındım").
# Someone else leaving counts too ("Elif Kervan'dan ayrıldı", "Ahmet doktorluğu bıraktı").
_LEFT = re.compile(
    r"\b(?:ayrild(?:im|ik|i)|birakt(?:im|ik|i)|istifa ett(?:im|ik|i)|cikt(?:im|ik))\b"
)
_LEAVING = re.compile(r"\b(?:ayril|birak|istifa|cik)")
_ARRIVED = re.compile(
    r"\b(?:tasin\w*|gec(?:tim|tik)|basla\w*|katil\w*|gir(?:dim|dik)|artik|simdi)\b"
)


# "geliştirici(si)" → "geliştir", "öğretmenlik" → "öğretmen": the word an occupation is made
# from ("Yazılım geliştiriciliğini bıraktım", "yazılım geliştirmiyor"; Phase 9.1).
_AGENT = re.compile(r"(?:[iu]c[iu]|c[iu])(?:l[iu](?:k|g[iu]\w*))?(?:s[iu])?$|l[iu](?:k|g[iu]\w*)$")


def occupation_stem(word: str) -> str:
    return _AGENT.sub("", word)


def left(clause: str, anchor: str | None) -> bool:
    """The clause says the user left ``anchor`` (a workplace, a city, a habit's object) — and
    ``anchor`` is not the leaving itself ("sigarayı bıraktım" as a value stays current)."""
    joined = " ".join(text.words(clause))
    if not _LEFT.search(joined) or _ARRIVED.search(joined):
        return False
    a = " ".join(text.words(anchor or ""))
    if not a or _LEAVING.search(a):
        return False
    words = text.words(clause)
    if text.mentions_name(words, a):
        return True
    # An occupation said with another ending ("geliştiriciliğini" for "geliştiricisi").
    *rest, last = a.split()
    stem = occupation_stem(last)
    return len(stem) >= 5 and any(
        w.startswith(stem) and all(any(b.startswith(r[:5]) for b in words[:i]) for r in rest)
        for i, w in enumerate(words)
    )


def tense_of(message: str, quote: str | None, anchor: str | None = None) -> Tense:
    return tense(clause_of(message, quote, anchor))


def change_marked(message: str) -> bool:
    """The user's words say something changed (or correct an earlier statement)."""
    return bool(_CHANGE.search(" ".join(text.words(message))))


def time_phrase(clause: str) -> str | None:
    """The time the user named ("2024'te", "geçen ay", "Mart 2025"), as written — never a
    computed date."""
    folded = text.fold(clause)
    m = _TIME_PHRASE.search(folded)
    if m is None:
        return None
    start, end = m.span(1)
    # The user's spelling, not the folded one (fold keeps positions for Turkish letters).
    original = clause[start:end] if len(clause) == len(folded) else m.group(1)
    return original.strip()[:40] or None
