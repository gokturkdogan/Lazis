"""DOIs in a reply: only those with a source are shown as identifiers (ADR-0022 §10).

LAZIS runs offline and cannot resolve a DOI. A DOI that looks well formed may still belong to
no publication, and the model writes such DOIs from memory (Phase 10B: 3 of 6 replies with no
request, 5 of 6 after "Bilmiyorsan uydur ama kaynak ver"). So a DOI in a reply is kept only
when it has a source LAZIS was given:

* **grounded** — it appears in what the model was sent (the user's messages, the information
  blocks, the recall note) or in an active memory record: kept as it is. That covers a DOI the
  user wrote and one from a local source. Kept is not verified: nothing here says it exists;
* **fiction** — the user's message asks for an example or fictional DOI ("örnek bir DOI
  formatı göster"): given, and the reply says it belongs to no publication unless it already
  does. Only a ``10.5555/`` example is kept as written; one with a publisher's prefix
  ("10.1038/…") may be a real publication's, so it becomes ``10.5555/ornek.0001``;
* **miscopied** — within two characters of exactly one grounded DOI: the model copied the
  user's (or a record's) DOI wrongly ("10.101038/nature14539" for "10.1038/nature14539"). It is
  written back as the source has it, not hidden as if LAZIS would not give the user's own DOI;
* **unsupported** — anything else: the identifier itself (with its ``doi.org`` link) is
  replaced in place by a plain Turkish phrase, and one sentence at the end says how to check
  the publication. Only the identifier is replaced; the rest of the reply (titles, authors,
  quotations, other references) is left as the model wrote it.

The guard streams: a DOI has no whitespace in it, so only a last word that could still become
one (a digit in it, or the start of "doi:" or a link) is held back; any other word is released
at once, with no lag added to the guards before it. The memory records are read while the
model writes (about 20 ms at 50,000 records): until they are in (:meth:`DoiGuard.add`), the
guard holds the reply from the first DOI that has no source yet.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from lazis.memory.commands import NOTICE_END, NOTICE_START
from lazis.storage.driver import Connection

# Crossref's recommended pattern (10.<4–9 digits>/<suffix>), with an optional doi.org link or
# "doi:" in front, and any letter in the suffix: the model writes "10.1016/j.neuroniño…" or
# "10.1000/test.örnek…", and an ASCII-only suffix would leave the rest of it in the reply. A
# suffix of at least 3 characters once trailing punctuation is cut: "10.2023/11." is a date.
_DOI = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/|\bdoi:\s?)?\b(10\.\d{4,9}/[-.;()/:\w]+)",
    re.IGNORECASE,
)
MIN_SUFFIX = 3
_TRAILING = ".,;:"

UNSUPPORTED = "doğrulayamadığım için yazmıyorum"  # in parentheses unless already in them
# The DOI is gone, but the title, authors and journal next to it are no more verified than it
# was: the sentence says so, without judging them (the guard is not a source checker).
UNSUPPORTED_NOTE = (
    "Buradaki DOI'yi ve yayın bilgilerini (başlık, yazar, dergi) doğrulayamıyorum, internete "
    "erişimim yok. Böyle bir yayın olup olmadığını ve doğru DOI'sini Crossref ya da Google "
    "Scholar'da aratarak kontrol edebilirsiniz."
)
UNSUPPORTED_NOTE_MANY = (
    "Buradaki DOI'leri ve yayın bilgilerini (başlık, yazar, dergi) doğrulayamıyorum, internete "
    "erişimim yok. Bu yayınların olup olmadığını ve doğru DOI'lerini Crossref ya da Google "
    "Scholar'da aratarak kontrol edebilirsiniz."
)
FICTION_NOTE = "(Bu DOI yalnızca bir örnektir; gerçek bir yayına ait değildir.)"
# An example DOI keeps only this prefix (Crossref's test prefix): one with a publisher's prefix
# ("10.1038/…", Nature) may be a real publication's, and the note above would then be false.
EXAMPLE_PREFIX = "10.5555/"

# The reply already says its DOI is not a real one (folded). "Örnek:" alone is not enough: it
# may introduce a real publication; nor is "uydurma" ("DOI uydurmam").
_SAYS_FICTION = re.compile(
    r"\b(kurgusal|hayali|temsili|varsayimsal)\w*|\b(sadece|yalnizca) (bir )?ornek"
    r"|\bornek amacl|\bgercek degil|\bgercek bir (doi|yayin|makale|kaynak|calisma)\w* (ait )?degil"
    r"|\bhicbir (gercek )?(yayin|makale|kaynak|calisma)\w* ait degil"
)
# The user asks for an example or fictional DOI, the DOI itself (not "örnek bir makale").
_ASKS_FICTION = re.compile(
    r"\b(ornek|kurgusal|hayali|uydurma|sahte|temsili|varsayimsal|rastgele|gercek olmayan)\b"
    r"[^.?!]{0,12}\bdoi"
    r"|\bdoi\w*\b[^.?!]{0,20}\b(ornegi|ornek|formati|formatini|bicimi|bicimini|nasil gorunur|"
    r"neye benzer)"
)
_MENTIONS_DOI = re.compile(r"\bdoi\w*\b")

_FOLD = str.maketrans("çğıöşüâîû", "cgiosuaiu")


def fold(text: str) -> str:
    return text.replace("İ", "i").replace("I", "ı").lower().translate(_FOLD)


def normalize(doi: str) -> str:
    """The DOI alone, lower case (DOIs are case-insensitive), without trailing punctuation or
    an unmatched closing parenthesis."""
    d = doi.lower()
    while d and (d[-1] in _TRAILING or (d[-1] == ")" and d.count("(") < d.count(")"))):
        d = d[:-1]
    return d


MAX_COPY_ERRORS = 2


def _distance(a: str, b: str) -> int:
    """Edit distance (insertions, deletions, substitutions)."""
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _valid(doi: str) -> bool:
    return len(doi.split("/", 1)[1]) >= MIN_SUFFIX


def find(text: str) -> list[str]:
    """The DOIs in a text, normalized."""
    return [d for m in _DOI.finditer(text) if _valid(d := normalize(m.group(1)))]


_STARTS = ("https://", "http://", "dx.doi.org/", "doi.org/", "doi:")


def _could_be_doi(word: str) -> bool:
    """The last word so far may still be or become (part of) a DOI."""
    w = word.lower().lstrip("(*_`[\"'")
    return (
        any(ch.isdigit() for ch in w)
        or "doi" in w
        or any(p.startswith(w) or w.startswith(p) for p in _STARTS if w)
    )


def grounded(texts: Iterable[str]) -> frozenset[str]:
    return frozenset(d for t in texts for d in find(t))


def asks_fiction(message: str) -> bool:
    """The user asks for an example or a fictional DOI ("kurgusal bir DOI yaz", "DOI formatı
    neye benzer?")."""
    return _ASKS_FICTION.search(fold(message)) is not None


def note(message: str) -> str:
    """For this request only, when the user's message speaks of a DOI. Empty otherwise."""
    if not _MENTIONS_DOI.search(fold(message)):
        return ""
    return "\n".join([
        NOTICE_START,
        "İnternete erişimin yok: bir DOI'nin gerçekten var olduğunu ya da hangi yayına ait "
        "olduğunu doğrulayamazsın. Kullanıcının verdiği ya da yukarıdaki bilgilerde geçen bir "
        "DOI'yi kullanabilirsin ama doğrulanmış gibi sunma. Bilmediğin bir DOI'yi yazma; "
        "bilmiyorsan bunu açıkça söyle. Kullanıcı açıkça örnek ya da kurgusal bir DOI isterse "
        "verebilirsin, gerçek bir yayına ait olmadığını belirterek.",
        NOTICE_END,
    ])  # fmt: skip


def local(conn: Connection) -> frozenset[str]:
    """DOIs in active memory records (a local source the reply may repeat)."""
    rows = conn.execute(
        "SELECT value, content FROM memories WHERE status = 'active'"
        " AND (instr(content, '10.') > 0 OR instr(value, '10.') > 0)"
    ).fetchall()
    return grounded(t for row in rows for t in row)


@dataclass
class DoiGuard:
    sources: frozenset[str] = frozenset()  # grounded DOIs, normalized
    fiction: bool = False  # the user asked for an example DOI
    complete: bool = True  # False until the memory records' DOIs are in (:meth:`add`)
    released: str = ""
    pending: str = ""
    replaced: list[str] = field(default_factory=list[str])  # unsupported DOIs, normalized
    kept: list[str] = field(default_factory=list[str])  # example DOIs left in
    swapped: int = 0  # example DOIs with a publisher's prefix, replaced by a plain example
    restored: list[str] = field(default_factory=list[str])  # miscopied, written as the source
    _before: str = ""

    def add(self, more: frozenset[str]) -> None:
        """The rest of the sources (memory records): the guard decides on everything now."""
        self.sources = self.sources | more
        self.complete = True

    def feed(self, chunk: str) -> str:
        self.pending += chunk
        cut = max(self.pending.rfind(" "), self.pending.rfind("\n"), self.pending.rfind("\t"))
        if not _could_be_doi(self.pending[cut + 1 :]):
            cut = len(self.pending) - 1
        if cut < 0:
            return ""
        ready, rest = self.pending[: cut + 1], self.pending[cut + 1 :]
        if not self.complete and not self.fiction:
            first = next((m for m in _DOI.finditer(ready) if self._unknown(m)), None)
            if first is not None:  # wait for the memory records before deciding on it
                return self._release(ready[: first.start()], ready[first.start() :] + rest)
        return self._release(ready, rest)

    def finish(self) -> str:
        self.complete = True
        out = self._release(self.pending, "")
        tail = ""
        if self.replaced:
            tail = UNSUPPORTED_NOTE_MANY if len(set(self.replaced)) > 1 else UNSUPPORTED_NOTE
        elif self.kept and (self.swapped or not _SAYS_FICTION.search(fold(self.released))):
            tail = FICTION_NOTE
        if tail:
            tail = ("\n\n" if self.released.strip() else "") + tail
            self.released += tail
        return out + tail

    def _release(self, ready: str, rest: str) -> str:
        self._before = self.released[-1:]  # what precedes ``ready`` (an opening parenthesis)
        piece = _DOI.sub(self._one, ready)
        self.pending = rest
        self.released += piece
        return piece

    def _copied_from(self, doi: str) -> str | None:
        """The one grounded DOI this one is a miscopy of, if any."""
        close = [
            s
            for s in self.sources
            if abs(len(s) - len(doi)) <= MAX_COPY_ERRORS and _distance(s, doi) <= MAX_COPY_ERRORS
        ]
        return close[0] if len(close) == 1 else None

    def _unknown(self, m: re.Match[str]) -> bool:
        doi = normalize(m.group(1))
        return _valid(doi) and doi not in self.sources

    def _one(self, m: re.Match[str]) -> str:
        doi = normalize(m.group(1))
        if not _valid(doi) or doi in self.sources:
            return m.group(0)
        if self.fiction:
            if doi.startswith(EXAMPLE_PREFIX):
                self.kept.append(doi)
                return m.group(0)
            # The example number is replaced by one that is plainly an example.
            example = f"{EXAMPLE_PREFIX}ornek.{len(self.kept) + 1:04d}"
            self.kept.append(example)
            self.swapped += 1
            whole = m.group(0)
            start = whole.lower().rfind(doi)
            return whole[:start] + example + whole[start + len(doi) :]
        whole = m.group(0)
        start = whole.lower().rfind(doi)
        source = self._copied_from(doi)
        if source is not None:
            self.restored.append(source)
            return whole[:start] + source + whole[start + len(doi) :]
        self.replaced.append(doi)
        # What normalize cut off (a full stop, a closing parenthesis) stays in the text.
        after = whole[start + len(doi) :]
        before = m.string[m.start() - 1] if m.start() > 0 else self._before
        if before == "(" and (after or m.string[m.end() : m.end() + 1]).startswith(")"):
            return UNSUPPORTED + after
        return f"({UNSUPPORTED})" + after
