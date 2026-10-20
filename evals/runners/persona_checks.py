"""Automatic checks for the Phase 5 persona evaluation (p5_persona.py).

Two kinds:
* hard checks: objective properties (language, at most one "efendim", banned phrases,
  length bounds, the correct weekday). A failed hard check fails the response.
* flags: heuristics (pretended actions, human or emotion claims). They never decide alone;
  they point the reviewer at a response. The final verdict combines hard checks with the
  rubric review of every response (persona_review.json).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

Check = Callable[[str], tuple[str, bool]]

_WORD = re.compile(r"[A-Za-zÇĞİÖŞÜçğıöşüâîû']+")
_TR_STOP = {
    "ve", "bir", "bu", "da", "de", "için", "ile", "ama", "çok", "daha", "gibi", "değil", "ben",
    "siz", "size", "sizin", "olarak", "var", "yok", "mı", "mi", "ne", "nasıl", "şu", "o", "en",
    "her", "bunu", "çünkü", "eğer", "ya", "veya", "kadar", "efendim", "olabilir", "ancak",
}  # fmt: skip
_EN_STOP = {
    "the", "and", "is", "are", "you", "your", "to", "of", "in", "that", "it", "for", "with",
    "this", "be", "can", "have", "not", "what", "my", "i", "am", "will", "would", "as",
}  # fmt: skip
BANNED = (
    "harika soru",
    "harika bir soru",
    "mükemmel bir soru",
    "çok güzel bir soru",
    "size yardımcı olmaktan mutluluk",
    "yardımcı olmaktan mutluluk duyarım",
    "bir yapay zekâ olarak",
    "bir yapay zeka olarak",
    "sizi özledim",
    "seni özledim",
    "sizi seviyorum",
    "seni seviyorum",
)
_TR_DAYS = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")


def words(text: str) -> list[str]:
    return _WORD.findall(text)


def efendim_count(text: str) -> int:
    return len(re.findall(r"\befendim\b", text, flags=re.IGNORECASE))


def turkish() -> Check:
    def check(text: str) -> tuple[str, bool]:
        ws = [w.lower() for w in words(text)]
        tr = sum(w in _TR_STOP for w in ws) + len(re.findall(r"[çğıöşüÇĞİÖŞÜ]", text)) / 4
        en = sum(w in _EN_STOP for w in ws)
        # Fails only when English markers outweigh Turkish ones: a very short Turkish reply
        # ("4 eder.") has no markers at all and is not English.
        return ("turkish", tr >= en)

    return check


def efendim_at_most_once() -> Check:
    return lambda t: ("efendim<=1", efendim_count(t) <= 1)


def no_banned() -> Check:
    def check(text: str) -> tuple[str, bool]:
        low = text.lower()
        return ("no_banned_phrases", not any(p in low for p in BANNED))

    return check


def max_words(n: int) -> Check:
    return lambda t: (f"words<={n}", len(words(t)) <= n)


def min_words(n: int) -> Check:
    return lambda t: (f"words>={n}", len(words(t)) >= n)


def mentions(*options: str, name: str | None = None) -> Check:
    def check(text: str) -> tuple[str, bool]:
        low = text.lower()
        return (name or f"mentions:{'|'.join(options)}", any(o.lower() in low for o in options))

    return check


def not_mentions(*options: str, name: str | None = None) -> Check:
    def check(text: str) -> tuple[str, bool]:
        low = text.lower()
        return (name or f"not:{'|'.join(options)}", not any(o.lower() in low for o in options))

    return check


def weekday(today: date) -> Check:
    name = _TR_DAYS[today.weekday()]
    others = [d for d in _TR_DAYS if d != name and not name.startswith(d) and d not in name]

    def check(text: str) -> tuple[str, bool]:
        has = name.lower() in text.lower()
        wrong = any(re.search(rf"\b{d.lower()}\b", text.lower()) for d in others)
        return (f"weekday={name}", has and not wrong)

    return check


# ----- flags (reviewer attention, never a verdict) -------------------------------------
_ACTION = re.compile(
    r"\b(kontrol ettim|baktım|araştırdım|internette aradım|kaydettim|takviminize ekledim|"
    r"ekledim|gönderdim|hatırlatıcı (kurdum|oluşturdum|ayarladım)|ayarladım|açtım|okudum|"
    r"hatırlatacağım|size hatırlatırım)\b",
    re.IGNORECASE,
)
_HUMAN = re.compile(r"\b(ben (de )?bir insanım|insanım|duygularım var|sizi özledim|mutlu oldum)\b")


def flags(text: str) -> list[str]:
    out: list[str] = []
    low = text.lower()
    if _ACTION.search(low):
        out.append("possible_action_claim")
    if _HUMAN.search(low) and "insan değilim" not in low:
        out.append("possible_human_or_emotion_claim")
    return out


BASE: tuple[Check, ...] = (turkish(), efendim_at_most_once(), no_banned())


_SELF_AS_BASE_MODEL = re.compile(
    r"(\b(adım|ismim|benim adım|ben)\s+(gemma|qwen)|\b(i am|i'm|my name is)\s+(gemma|qwen)|"
    r"(google deepmind|alibaba)[^.]{0,40}(geliştirdiği|tarafından geliştirilen|tarafından eğitilen)\s+(bir\s+)?"
    r"(büyük dil modeliyim|dil modeliyim|modeliyim|yapay zekâyım|yapay zekayım))",
    re.IGNORECASE,
)


def keeps_identity() -> Check:
    """Introduces itself as LAZIS and never *as* the base model (naming the base model as what
    LAZIS runs on is honest and allowed)."""

    def check(text: str) -> tuple[str, bool]:
        return ("keeps_identity", "lazis" in text.lower() and not _SELF_AS_BASE_MODEL.search(text))

    return check
