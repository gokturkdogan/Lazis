"""Turkish-aware text helpers for memory matching and search (no external stemmer).

* ``casefold``: Turkish casing (İ→i, I→ı) before lowering; Python's ``lower()`` maps I→i.
* ``fold``: casefold plus diacritic folding (ç→c, ğ→g, ı→i, ö→o, ş→s, ü→u), so "sirket" finds
  "şirket". Everything indexed and every query goes through ``fold``.
* ``name_key``: a person/project name without apostrophe suffixes ("Ahmet'in" → "ahmet").
* ``query_terms``: FTS5 prefix terms tolerant of Turkish agglutination ("bilgisayarım" →
  ``bilgisay*``), dropping stop words.
"""

from __future__ import annotations

import re
import unicodedata

_FOLD = str.maketrans(
    {"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u"}
)
_WORD = re.compile(r"[0-9a-zçğıöşüâîû]+")
_APOSTROPHE = re.compile(r"['’`´]")

# Function words and very common verbs that carry no search value.
STOP_WORDS = frozenset(
    {
        "ve",
        "veya",
        "ile",
        "ama",
        "fakat",
        "ancak",
        "ki",
        "de",
        "da",
        "mi",
        "mı",
        "mu",
        "mü",
        "ne",
        "neden",
        "nasil",
        "nasıl",
        "niye",
        "hangi",
        "hangisi",
        "kim",
        "kimin",
        "bir",
        "bu",
        "su",
        "şu",
        "o",
        "ben",
        "sen",
        "biz",
        "siz",
        "onlar",
        "benim",
        "senin",
        "bizim",
        "sizin",
        "onun",
        "bana",
        "sana",
        "bize",
        "size",
        "beni",
        "seni",
        "bizi",
        "sizi",
        "icin",
        "için",
        "gibi",
        "kadar",
        "daha",
        "cok",
        "çok",
        "az",
        "en",
        "her",
        "hic",
        "hiç",
        "bazi",
        "bazı",
        "tum",
        "tüm",
        "var",
        "yok",
        "evet",
        "hayir",
        "hayır",
        "olarak",
        "olan",
        "oldu",
        "olur",
        "olsun",
        "degil",
        "değil",
        "misin",
        "miyim",
        "mısın",
        "musun",
        "simdi",
        "şimdi",
        "bugun",
        "bugün",
        "dun",
        "dün",
        "yarin",
        "yarın",
        "artik",
        "artık",
        "sonra",
        "once",
        "önce",
        "hep",
        "hala",
        "hâlâ",
        "zaten",
        "lazis",
        "efendim",
        "lutfen",
        "lütfen",
        "tamam",
        "peki",
        "bunu",
        "sunu",
        "şunu",
        "onu",
        "bunlar",
        "şunlar",
        "sey",
        "şey",
        "seyler",
        "şeyler",
        "diye",
        "dedi",
        "diyor",
        "biliyor",
        "biliyorsun",
        "hatirliyor",
        "hatırlıyor",
        "neydi",
        "nedir",
        "ediyor",
        "yapiyor",
        "yapıyor",
    }
)


def casefold(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return text.replace("İ", "i").replace("I", "ı").lower()


def fold(text: str) -> str:
    return casefold(text).translate(_FOLD)


def words(text: str) -> list[str]:
    """Folded word tokens (apostrophes split proper-noun suffixes off)."""
    return _WORD.findall(fold(_APOSTROPHE.sub(" ", text)))


def name_key(name: str) -> str:
    """Comparable key for an entity name or alias: folded words, apostrophe suffixes dropped."""
    parts: list[str] = []
    for raw in casefold(name).split():
        base = _APOSTROPHE.split(raw, maxsplit=1)[0]
        parts.append(base.translate(_FOLD))
    return " ".join(w for w in (re.sub(r"[^0-9a-z]", "", p) for p in parts) if w)


def stem_prefix(word: str) -> str:
    """A prefix that survives most Turkish suffix chains ("bilgisayarımdaki" and "bilgisayar"
    share it): short words keep 4 letters, longer ones about two thirds (at least 5)."""
    if len(word) <= 4:
        return word
    if len(word) <= 6:
        return word[:4]
    return word[: max(5, round(len(word) * 0.65))]


def query_terms(text: str, *, limit: int = 12) -> list[str]:
    """Distinct FTS5 prefix terms for a free-text query (folded, stop words removed)."""
    seen: list[str] = []
    for w in words(text):
        if w in STOP_WORDS or (len(w) < 3 and not (w.isdigit() and len(w) >= 2)):
            continue
        p = stem_prefix(w)
        if p not in seen:
            seen.append(p)
        if len(seen) >= limit:
            break
    return seen


def fts_match(terms: list[str]) -> str | None:
    """An FTS5 MATCH expression OR-ing prefix terms (terms are [0-9a-z] only, so safe)."""
    safe = [t for t in terms if re.fullmatch(r"[0-9a-z]+", t)]
    return " OR ".join(f"{t}*" for t in safe) or None


def mentions_name(text_words: list[str], key: str) -> bool:
    """True if a folded multi-word name ``key`` appears in ``text_words``, allowing Turkish
    suffixes on the last word without an apostrophe ("ahmetle", "ahmetin")."""
    parts = key.split()
    if not parts:
        return False
    n = len(parts)
    for i in range(len(text_words) - n + 1):
        window = text_words[i : i + n]
        if window[:-1] != parts[:-1]:
            continue
        last, want = window[-1], parts[-1]
        if last == want or (
            last.startswith(want) and len(last) - len(want) <= 5 and len(want) >= 3
        ):
            return True
    return False


def candidate_keys(text_words: list[str], *, max_words: int = 4) -> set[str]:
    """Every alias key ``mentions_name`` could match in these words: spans of up to
    ``max_words`` words whose last word may carry up to 5 suffix letters ("ahmetin")."""
    keys: set[str] = set()
    for i in range(len(text_words)):
        for n in range(1, max_words + 1):
            if i + n > len(text_words):
                break
            head, last = text_words[i : i + n - 1], text_words[i + n - 1]
            keys.add(" ".join([*head, last]))
            for k in range(max(3, len(last) - 5), len(last)):
                keys.add(" ".join([*head, last[:k]]))
    return keys


def similarity(a: str, b: str) -> float:
    """Jaccard similarity of folded word sets (cheap near-duplicate test)."""
    sa, sb = set(words(a)) - STOP_WORDS, set(words(b)) - STOP_WORDS
    if not sa or not sb:
        return 1.0 if fold(a).strip() == fold(b).strip() else 0.0
    return len(sa & sb) / len(sa | sb)
