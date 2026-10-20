"""Deterministic relationship queries (MEMORY_ARCHITECTURE P7.5, ADR-0016 decision 7).

The graph answers; the model only words the answer. A question is parsed here into a typed
query, run as a bounded walk over **stored** relationships (current ones unless the query
asks about the past), and returned as a result with its supporting path — or as "no record",
"which Ahmet?", or "nobody by that name". Nothing is inferred: a friend's sibling is never
the user's friend, and a chain that breaks is reported as broken.

Bounds: at most 3 steps, cycle-free paths (no person twice), at most ``MAX_PATHS`` paths and
``MAX_FANOUT`` relationships per person. Sensitive relationships (an intimate partner) appear
only when the question names that type, never in a neighbour list or a connecting path.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from lazis.memory import graphstore as gs
from lazis.memory import relations, text
from lazis.memory import repository as repo
from lazis.memory.models import CURRENT, USER_ID, Entity, Relationship
from lazis.storage.driver import Connection

MAX_HOPS = 3
MAX_PATHS = 50
MAX_FANOUT = 200
MAX_FRONTIER = 400
MAX_LISTED = 10  # results or paths written out for the model
MAX_NEIGHBOURS = 30

# ----- paths --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Hop:
    """One relationship read from ``frm``: ``to`` is ``frm``'s ⟨type⟩ (``inverted``: an
    affiliation or one-way relationship read from its target — "Ahmet: Kervan'ın çalışanı")."""

    rel: Relationship
    frm: str
    to: str
    type: str
    inverted: bool


@dataclass(frozen=True)
class Path:
    start: str
    hops: tuple[Hop, ...] = ()

    @property
    def end(self) -> str:
        return self.hops[-1].to if self.hops else self.start

    @property
    def nodes(self) -> tuple[str, ...]:
        return (self.start, *(h.to for h in self.hops))

    def plus(self, hop: Hop) -> Path:
        return Path(self.start, (*self.hops, hop))


def reading(rel: Relationship, node: str) -> Hop | None:
    """The relationship as seen from ``node`` (one of its ends)."""
    if rel.source_id == node:
        return Hop(rel, node, rel.target_id, rel.type, False)
    if rel.target_id != node or relations.get(rel.type) is None:
        return None
    back = relations.reading_from_target(rel.type)
    if back is not None:
        return Hop(rel, node, rel.source_id, back, False)
    return Hop(rel, node, rel.source_id, rel.type, True)


class _Graph:
    """Adjacency loaded on demand in batches, plus an entity cache, for one query."""

    def __init__(
        self,
        conn: Connection,
        *,
        statuses: Sequence[str] = CURRENT,
        allow: frozenset[str] = frozenset(),
    ) -> None:
        self.conn = conn
        self.statuses = tuple(statuses)
        self.allow = allow
        self._adj: dict[str, list[Hop]] = {}
        self._entities: dict[str, Entity | None] = {}
        self._status: dict[str, str] = {}

    def load(self, ids: Sequence[str]) -> None:
        missing = [i for i in dict.fromkeys(ids) if i not in self._adj]
        for i in missing:
            self._adj[i] = []
        if not missing:
            return
        edges = gs.edges_touching(self.conn, missing, self.statuses)
        for node, rel in sorted(edges, key=lambda x: x[1].id):  # ULIDs: the order stated
            if rel.sensitivity == "sensitive" and rel.type not in self.allow:
                continue
            hop = reading(rel, node)
            if hop is not None and len(self._adj[node]) < MAX_FANOUT:
                self._adj[node].append(hop)
        others = [h.to for i in missing for h in self._adj[i] if h.to not in self._status]
        self._status.update(gs.entity_statuses(self.conn, others))

    def hops(self, node: str) -> list[Hop]:
        self.load([node])
        return [h for h in self._adj[node] if self.active(h.to)]

    def entity(self, eid: str) -> Entity | None:
        if eid not in self._entities:
            self._entities[eid] = repo.get_entity(self.conn, eid)
        return self._entities[eid]

    def active(self, eid: str) -> bool:
        if eid not in self._status:
            self._status.update(gs.entity_statuses(self.conn, [eid]))
        return self._status.get(eid) == "active"

    def name(self, eid: str) -> str:
        e = self.entity(eid)
        return "Kullanıcı" if e is None or e.is_user else e.name


@dataclass(frozen=True)
class Step:
    """One relation asked for: the readings whose type is in ``types`` (and direction)."""

    key: str
    types: tuple[str, ...]
    inverted: bool = False
    only: tuple[str, ...] | None = None  # an appositive name: "kardeşi Mehmet'in"
    label: str = ""

    @staticmethod
    def of(key: str, *, inverted: bool = False) -> Step:
        t = relations.TYPES[key]
        return Step(key, relations.answers(key), inverted, None,
                    t.inverse_label if inverted else t.label)  # fmt: skip

    def matches(self, hop: Hop) -> bool:
        return (
            hop.inverted == self.inverted
            and hop.type in self.types
            and (self.only is None or hop.to in self.only)
        )


def follow(
    conn: Connection, start: str, steps: Sequence[Step], *, statuses: Sequence[str] = CURRENT
) -> tuple[list[Path], list[Path], int]:
    """Walk ``steps`` from ``start``. Returns (complete paths, the deepest partial paths, the
    number of steps that matched). Cycle-free: a path never visits a person twice."""
    allow = frozenset(t for s in steps for t in s.types if _sensitive(t))
    g = _Graph(conn, statuses=statuses, allow=allow)
    paths = [Path(start)]
    for k, step in enumerate(steps):
        g.load([p.end for p in paths][:MAX_FRONTIER])
        nxt = [
            p.plus(h)
            for p in paths[:MAX_FRONTIER]
            for h in g.hops(p.end)
            if step.matches(h) and h.to not in p.nodes
        ][:MAX_PATHS]
        if not nxt:
            return [], paths, k
        paths = nxt
    return paths, paths, len(steps)


def paths_between(
    conn: Connection, a: str, b: str, *, max_hops: int = MAX_HOPS, limit: int = MAX_PATHS
) -> list[Path]:
    """Cycle-free paths of 1..``max_hops`` current, non-sensitive relationships from ``a`` to
    ``b`` (meet in the middle: two levels from ``a``, one from ``b``), shortest first."""
    if a == b:
        return []
    g = _Graph(conn)
    g.load([a, b])
    found: list[Path] = []
    first = [Path(a).plus(h) for h in g.hops(a) if h.to != a]
    found += [p for p in first if p.end == b]
    if max_hops >= 2:
        into_b: dict[str, list[Hop]] = {}
        for h in g.hops(b):
            into_b.setdefault(h.to, []).append(h)
        mids = [p for p in first if p.end != b]
        for p in mids:  # a → x → b
            for back in into_b.get(p.end, []):
                hop = reading(back.rel, back.to)
                if hop is not None:
                    found.append(p.plus(hop))
        if max_hops >= 3:
            g.load([p.end for p in mids][:MAX_FRONTIER])
            for p in mids[:MAX_FRONTIER]:  # a → x → y → b
                for h in g.hops(p.end):
                    if h.to in (a, b) or h.to in p.nodes:
                        continue
                    for back in into_b.get(h.to, []):
                        hop = reading(back.rel, back.to)
                        if hop is not None:
                            found.append(p.plus(h).plus(hop))
                if len(found) >= limit * 4:
                    break
    found.sort(key=lambda p: (len(p.hops), -min(h.rel.confidence for h in p.hops)))
    return found[:limit]


def neighbours(
    conn: Connection,
    eid: str,
    *,
    categories: Sequence[str] | None = None,
    statuses: Sequence[str] = CURRENT,
) -> list[Hop]:
    """Direct relationships of one entity, read from it (non-sensitive only)."""
    g = _Graph(conn, statuses=statuses)
    out = [
        h
        for h in g.hops(eid)
        if categories is None or relations.TYPES[h.rel.type].category in categories
    ]
    return out[:MAX_NEIGHBOURS]


def _sensitive(key: str) -> bool:
    t = relations.get(key)
    return t is not None and t.sensitivity == "sensitive"


# ----- Turkish rendering --------------------------------------------------------------------
def _marks(rel: Relationship) -> str:
    notes: list[str] = []
    if rel.status == "planned":
        notes.append("planlanan")
    elif rel.status == "unverified":
        notes.append("doğrulanmamış")
    elif rel.status == "ended":
        notes.append("geçmişte; artık geçerli değil")
    if rel.time_text:
        notes.append(rel.time_text)
    if rel.conflict_state == "pending":
        notes.append("bununla çelişen bir bilgi onay bekliyor")
    return f" ({'; '.join(notes)})" if notes else ""


def hop_text(g: _Graph, hop: Hop) -> str:
    """ "Mehmet: Ahmet'in kardeşi" (read from Ahmet). An affiliation or one-way relationship
    read from its target is said the way it was stored: "Kervan: Mehmet'in çalıştığı yer"."""
    if hop.inverted:
        line = relations.describe(g.name(hop.rel.source_id), hop.rel.type,
                                  g.name(hop.rel.target_id))  # fmt: skip
    else:
        label = relations.TYPES[hop.type].label
        line = f"{g.name(hop.to)}: {relations.genitive(g.name(hop.frm))} {label}"
    return line + _marks(hop.rel)


def path_text(g: _Graph, path: Path) -> str:
    return " → ".join(hop_text(g, h) for h in path.hops)


# ----- questions ----------------------------------------------------------------------------
QueryKind = Literal["chain", "path", "neighbours", "who"]


@dataclass(frozen=True)
class NameRef:
    """Who a query starts from: the user, the entities a name matched, or an unknown name."""

    surface: str
    ids: tuple[str, ...] = ()
    user: bool = False
    via: str | None = None  # "çocukluk arkadaşım Ahmet": only an Ahmet who is that to the user


USER = NameRef("Kullanıcı", (USER_ID,), user=True)


@dataclass(frozen=True)
class Query:
    kind: QueryKind
    start: NameRef
    steps: tuple[Step, ...] = ()
    other: NameRef | None = None
    categories: tuple[str, ...] | None = None
    check: tuple[str, ...] | None = None  # "... Mehmet mi?": is the answer this person?


@dataclass(frozen=True)
class _El:
    kind: Literal["rel", "name", "self", "unknown", "word"]
    word: str = ""
    key: str = ""
    ending: str = ""
    first: bool = False
    ids: tuple[str, ...] = ()
    surface: str = ""


_RAW_WORD = re.compile(r"[0-9A-Za-zÇĞİÖŞÜÂÎÛçğıöşüâîû]+")
_APOS = re.compile(r"['’`´]")
SELF_WORDS = frozenset({"ben", "benim", "beni", "bana", "benimle", "bende", "benden"})
Q_WORDS = frozenset({"kim", "kimdir", "kimdi", "kimler", "kimlerdir", "kimlerdi", "kimmis",
                     "kimlermis", "hangisi", "hangileri"})  # fmt: skip
_NAME_Q = (frozenset({"adi", "ismi", "adlari", "isimleri"}), frozenset({"ne", "nedir", "neydi"}))
_YESNO = frozenset({"mi", "mu", "midir", "mudur"})
_GENITIVE = re.compile(r"(?:n?in|n?un)$")
_LOCATIVE = re.compile(r"(?:n?d[ae]|n?t[ae])$")
_KIND_NOUNS = ("proje", "sirket", "firma", "kurum", "sirke", "ekib", "takim")


@dataclass(frozen=True)
class _Tok:
    word: str  # folded
    apos: str  # folded ending written after an apostrophe ("in" in "Ahmet'in")
    raw: str


def _tokens(question: str) -> list[_Tok]:
    out: list[_Tok] = []
    for chunk in question.split():
        parts = _APOS.split(chunk, maxsplit=1)
        bases = _RAW_WORD.findall(parts[0])
        tail = _RAW_WORD.findall(parts[1]) if len(parts) > 1 else []
        for n, raw in enumerate(bases):
            apos = text.fold(tail[0]) if tail and n == len(bases) - 1 else ""
            out.append(_Tok(text.fold(raw), apos, raw))
    return out


def _alias_hits(conn: Connection, toks: Sequence[_Tok]) -> dict[str, list[str]]:
    """alias key → active entity ids, for every key that could occur in the question."""
    keys: set[str] = set()
    words = [t.word for t in toks]
    for i in range(len(words)):
        for n in range(1, 4):
            if i + n > len(words):
                break
            head, last = words[i : i + n - 1], words[i + n - 1]
            for k in range(max(3, len(last) - 5), len(last) + 1):
                keys.add(" ".join([*head, last[:k]]))
            keys.add(" ".join([*head, last]))
    hits: dict[str, list[str]] = {}
    ordered = sorted(keys)
    for i in range(0, len(ordered), 400):
        chunk = ordered[i : i + 400]
        rows = conn.execute(
            "SELECT a.alias_key, a.entity_id FROM memory_entity_aliases a"  # noqa: S608
            " JOIN memory_entities e ON e.id = a.entity_id"
            f" WHERE e.status = 'active' AND a.alias_key IN ({','.join('?' * len(chunk))})"
            " ORDER BY e.created_at",
            chunk,
        ).fetchall()
        for key, eid in rows:
            ids = hits.setdefault(str(key), [])
            if str(eid) not in ids:
                ids.append(str(eid))
    return hits


def _elements(conn: Connection, question: str) -> list[_El]:
    toks = _tokens(question)
    words = [t.word for t in toks]
    hits = _alias_hits(conn, toks)
    els: list[_El] = []
    i = 0
    while i < len(toks):
        w = words[i]
        if w in SELF_WORDS:
            els.append(_El("self", word=w))
            i += 1
            continue
        m = relations.match_at(words, i)
        if m is not None:
            key, n, ending = m
            els.append(_El("rel", word=w, key=key, ending=ending,
                           first=relations.first_person(ending)))  # fmt: skip
            i += n
            continue
        span = _name_at(words, i, hits)
        if span is not None:
            n, key, ending = span
            last = toks[i + n - 1]
            ending += last.apos
            surface = " ".join(t.raw for t in toks[i : i + n])
            els.append(_El("name", word=w, ending=ending, ids=tuple(hits[key]), surface=surface))
            i += n
            continue
        tok = toks[i]
        if tok.raw[:1].isupper() and (tok.apos or i > 0) and w not in Q_WORDS:
            els.append(_El("unknown", word=w, ending=tok.apos, surface=tok.raw))
        else:
            els.append(_El("word", word=w, ending=tok.apos))
        i += 1
    return els


def _name_at(
    words: Sequence[str], i: int, hits: dict[str, list[str]]
) -> tuple[int, str, str] | None:
    """The longest alias at ``words[i]``: (words used, alias key, ending without apostrophe)."""
    for n in (3, 2, 1):
        if i + n > len(words):
            continue
        head, last = words[i : i + n - 1], words[i + n - 1]
        for k in range(len(last), max(3, len(last) - 5) - 1, -1):
            key = " ".join([*head, last[:k]])
            if key in hits and (k == len(last) or len(last[:k]) >= 3):
                return n, key, last[k:]
    return None


def _is_question(rest: Sequence[_El], qmark: bool) -> bool:
    if not rest:
        return qmark
    w = rest[0].word
    if rest[0].kind == "word" and w in Q_WORDS:
        return True
    return w in _NAME_Q[0] and len(rest) > 1 and rest[1].word in _NAME_Q[1]


def _ref(el: _El) -> NameRef:
    if el.kind == "self":
        return USER
    return NameRef(el.surface, el.ids)


def parse(conn: Connection, question: str) -> Query | None:
    """The relationship query in a question, or None (not a relationship question)."""
    els = _elements(conn, question)
    qmark = "?" in question
    return (
        _parse_path(els, qmark)
        or _parse_neighbours(els, qmark)
        or _parse_affiliation(els)
        or _parse_chain(els, qmark)
        or _parse_who(els, qmark)
    )


def _named(el: _El) -> bool:
    return el.kind in ("name", "unknown", "self")


def _parse_chain(els: Sequence[_El], qmark: bool) -> Query | None:
    for s in range(len(els)):
        e = els[s]
        j = s
        if e.kind == "self":
            j += 1
            if j >= len(els) or els[j].kind != "rel" or not els[j].first:
                continue
            e = els[j]
        steps: list[Step] = []
        if e.kind in ("name", "unknown") and _GENITIVE.search(e.ending):
            start = _ref(e)
            j += 1
        elif e.kind == "rel" and e.first:
            nxt = els[j + 1] if j + 1 < len(els) else None
            if nxt is not None and nxt.kind in ("name", "unknown") and _GENITIVE.search(nxt.ending):
                start = replace(_ref(nxt), via=e.key)  # "çocukluk arkadaşım Ahmet'in ..."
                j += 2
            else:
                start = USER
                steps.append(Step.of(e.key))
                j += 1
        else:
            continue
        check: tuple[str, ...] | None = None
        while j < len(els) and els[j].kind == "rel" and not els[j].first:
            step = Step.of(els[j].key)
            j += 1
            if j < len(els) and els[j].kind == "name":
                after = els[j + 1 : j + 2]
                if after and after[0].kind == "rel":  # "kardeşi Mehmet'in eşi"
                    step = replace(step, only=els[j].ids)
                    j += 1
                elif after and after[0].word in _YESNO:  # "kardeşi Mehmet mi?"
                    check = els[j].ids
                    j += 2
                    steps.append(step)
                    return Query("chain", start, tuple(steps), check=check)
            steps.append(step)
        if steps and _is_question(els[j:], qmark):
            return Query("chain", start, tuple(steps))
        tail = _tail_step(_words(els[j:]))
        if tail is not None and (steps or j > s):  # "Ahmet'in kardeşi nerede çalışıyor"
            return Query("chain", start, (*steps, tail))
    return None


def _words(els: Sequence[_El]) -> list[str]:
    return [e.word for e in els if e.kind == "word"]


_ASKING = frozenset({"kim", "kimler", "ne", "neler", "nedir", "hakkinda", "mi", "mu", "musun",
                     "misin", "nasil", "nereden", "nerden", "hangi"})  # fmt: skip


def _asks(ws: Sequence[str], qmark: bool) -> bool:
    """A question or a request to tell, not a statement ("ailemle tatile gittik")."""
    return qmark or any(
        w in _ASKING or w.startswith(("biliyor", "anlat", "soyle", "listele", "say")) for w in ws
    )


def _tail_step(ws: Sequence[str]) -> Step | None:
    """ "… nerede çalışıyor", "… nerede yaşıyor", "… hangi projede çalışıyor"."""
    if not ws:
        return None
    if ws[0].startswith("calistig"):  # "Mehmet'in çalıştığı yer neresi"
        return Step("works_at", ("works_at", "works_in_place"), False, None, "çalıştığı yer")
    if ws[0].startswith(("yasadig", "oturdug")):
        return Step.of("lives_in")
    where = ws[0] in ("nerede", "nerde")
    if where and len(ws) > 1 and ws[1].startswith("calis"):
        return Step("works_at", ("works_at", "works_in_place"), False, None, "çalıştığı yer")
    if where and len(ws) > 1 and ws[1].startswith(("yasi", "otur")):
        return Step.of("lives_in")
    if ws[0] == "hangi" and len(ws) > 2 and ws[1].startswith("proje") and ws[2].startswith("calis"):
        return Step("works_on", ("works_on", "develops", "contributes_to"), False, None,
                    "çalıştığı proje")  # fmt: skip
    if (
        ws[0] == "hangi"
        and len(ws) > 2
        and ws[1].startswith(_KIND_NOUNS)
        and ws[2].startswith("calis")
    ):
        return Step.of("works_at")
    return None


def _parse_path(els: Sequence[_El], qmark: bool) -> Query | None:
    named = [e for e in els if _named(e)]
    ws = _words(els)
    if not _asks(ws, qmark):
        return None
    knows = any(w.startswith("tani") for w in ws)
    how = any(w in ("nereden", "nerden", "nasil") for w in ws)
    if len(named) == 1 and named[0].kind != "self" and knows and how:
        return Query("path", USER, other=_ref(named[0]))
    linked = any(w.startswith(("arasinda", "baglant", "bagli", "bagliyor", "iliski", "akraba"))
                 for w in ws) or (knows and any(w.startswith("birbir") for w in ws))  # fmt: skip
    kin_check = any(e.kind == "rel" for e in els) and any(w in _YESNO for w in ws)
    linked = linked or kin_check or any(w.startswith("evli") for w in ws)  # "… kardeş mi?"
    if len(named) >= 2 and linked:
        joined = any(w in ("ile", "ve") for w in ws) or re.search(r"y?l[ae]$", named[0].ending)
        if joined:
            return Query("path", _ref(named[0]), other=_ref(named[1]))
    return None


_FAMILY = ("family",)
_WORK = ("work", "organization", "project")


def _parse_neighbours(els: Sequence[_El], qmark: bool) -> Query | None:
    ws = _words(els)
    if not _asks(ws, qmark):
        return None
    named = [e for e in els if _named(e)]
    who = named[0] if len(named) == 1 else None
    if any(w.startswith(("ailem", "akrabalarim")) for w in ws) and not named:
        return Query("neighbours", USER, categories=_FAMILY)
    if who is None:
        return None
    if any(w.startswith(("ailesi", "akrabalari", "ailesin")) for w in ws):
        return Query("neighbours", _ref(who), categories=_FAMILY)
    if "kimlerle" in ws or any(w.startswith(("baglantilari", "cevresi")) for w in ws):
        cats = _WORK if "is" in ws or any(w.startswith("calis") for w in ws) else None
        return Query("neighbours", _ref(who), categories=cats)
    return None


_WORKS = ("works_at", "works_on", "develops", "contributes_to", "manages", "member_of")


def _parse_affiliation(els: Sequence[_El]) -> Query | None:
    named = [e for e in els if e.kind in ("name", "unknown")]
    ws = _words(els)
    if len(named) != 1 or not any(w.startswith(("calis", "yasi", "otur")) for w in ws):
        return None
    who = named[0]
    ref = _ref(who)
    i = els.index(who)
    nxt = els[i + 1].word if i + 1 < len(els) else ""
    located = _LOCATIVE.search(who.ending) or (
        nxt.startswith(_KIND_NOUNS) and _LOCATIVE.search(nxt)
    )
    if located and any(w in Q_WORDS for w in ws):  # "Pusula projesinde kim çalışıyor"
        step = Step("works", _WORKS, True, None, "çalışanı")
        return Query("chain", ref, (step,))
    if who.ending:
        return None
    tail = _tail_step(_words(els[i + 1 :]))  # "Ahmet nerede çalışıyor"
    return None if tail is None else Query("chain", ref, (tail,))


def _parse_who(els: Sequence[_El], qmark: bool) -> Query | None:
    core = [e for e in els if not (e.kind == "word" and e.word in ("peki", "sence", "acaba"))]
    if (
        len(core) == 2
        and core[0].kind in ("name", "unknown")
        and not core[0].ending
        and core[1].kind == "word"
        and core[1].word in ("kim", "kimdir", "kimdi")
    ):
        return Query("who", _ref(core[0]))
    return None


# ----- answers ------------------------------------------------------------------------------
Status = Literal["unique", "several", "none", "ambiguous", "unknown"]


@dataclass(frozen=True)
class Answer:
    query: Query
    status: Status
    lines: tuple[str, ...]  # for the model: facts with their support, or what is missing
    results: tuple[str, ...] = ()  # entity ids
    paths: tuple[Path, ...] = ()
    options: tuple[Entity, ...] = ()  # status "ambiguous": the people a name could mean
    unresolved: str | None = None  # the name that was ambiguous or unknown
    relationship_ids: tuple[str, ...] = field(default=())  # every relationship used


def _resolve(conn: Connection, ref: NameRef) -> tuple[list[str], list[Entity]]:
    """(ids, all candidates) for a reference, applying an appositive relation filter."""
    if ref.user:
        return [USER_ID], []
    cands = [e for e in (repo.get_entity(conn, i) for i in ref.ids) if e is not None]
    cands = [e for e in cands if e.status == "active"]
    if ref.via is None:
        return [e.id for e in cands], cands
    step = Step.of(ref.via)
    linked = {h.to for h in _Graph(conn).hops(USER_ID) if step.matches(h)}
    return [e.id for e in cands if e.id in linked], cands


def _label(e: Entity) -> str:
    return f"{e.name} ({e.relation})" if e.relation else e.name


def _describe_chain(g: _Graph, start: str, steps: Sequence[Step]) -> str:
    parts = [relations.genitive(g.name(start))]
    for k, step in enumerate(steps):
        last = k == len(steps) - 1
        parts.append(step.label if last else relations.genitive_of_noun(step.label))
    return " ".join(parts)


def _start_problem(conn: Connection, q: Query, ref: NameRef, ids: list[str],
                   cands: list[Entity]) -> Answer | None:  # fmt: skip
    if ref.user:
        return None
    if not cands:
        line = f"Kişisel hafızada «{ref.surface}» adlı bir kayıt yok."
        return Answer(q, "unknown", (line,), unresolved=ref.surface)
    if ref.via is not None and not ids:
        rel = relations.TYPES[ref.via].label
        line = f"Kullanıcının {rel} olarak kayıtlı bir «{ref.surface}» yok."
        return Answer(q, "none", (line,), unresolved=ref.surface)
    if len(ids) > 1:
        options = tuple(e for e in cands if e.id in ids)
        names = ", ".join(_label(e) for e in options)
        line = (f"Hafızada birden fazla «{ref.surface}» var: {names}. Hangisinin kastedildiğini "
                "sor; tahmin etme.")  # fmt: skip
        return Answer(q, "ambiguous", (line,), options=options, unresolved=ref.surface)
    return None


def answer(conn: Connection, q: Query) -> Answer:
    ids, cands = _resolve(conn, q.start)
    problem = _start_problem(conn, q, q.start, ids, cands)
    if problem is not None:
        return problem
    start = ids[0]
    if q.kind == "chain":
        return _answer_chain(conn, q, start)
    if q.kind == "path":
        assert q.other is not None
        oids, ocands = _resolve(conn, q.other)
        problem = _start_problem(conn, q, q.other, oids, ocands)
        if problem is not None:
            return problem
        return _answer_path(conn, q, start, oids[0])
    if q.kind == "neighbours":
        return _answer_neighbours(conn, q, start)
    return _answer_who(conn, q, start)


def _rel_ids(paths: Sequence[Path]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(h.rel.id for p in paths for h in p.hops))


def _answer_chain(conn: Connection, q: Query, start: str) -> Answer:
    g = _Graph(conn)
    asked = _describe_chain(g, start, q.steps)
    complete, partial, reached = follow(conn, start, q.steps)
    lines = [f"Soru: {asked}"]
    if not complete:
        rest = q.steps[reached:]
        heads = list(dict.fromkeys(p.end for p in partial))
        if reached:
            known = "; ".join(path_text(g, p) for p in partial[:MAX_LISTED])
            lines.append(f"Bilinen: {known}")
        missing = " / ".join(_describe_chain(g, h, rest) for h in heads[:3])
        lines.append(f"Cevap: kayıt yok — {missing} kişisel hafızada kayıtlı değil. Tahmin etme.")
        if len(rest) == 1:  # the relation may have ended: say so rather than "unknown"
            past = [p for h in heads for p in follow(conn, h, rest, statuses=("ended",))[0]]
            if past:
                lines.append(
                    "Geçmiş kayıt: " + "; ".join(path_text(g, p) for p in past[:MAX_LISTED])
                )
        used = partial if reached else []
        return Answer(q, "none", tuple(lines), paths=tuple(used), relationship_ids=_rel_ids(used))
    ends = list(dict.fromkeys(p.end for p in complete))
    if q.check is not None:
        hit = [p for p in complete if p.end in q.check]
        if hit:
            lines.append(f"Cevap: evet — {g.name(hit[0].end)}.")
            lines.append(f"Dayanak: {path_text(g, hit[0])}")
            return Answer(q, "unique", tuple(lines), (hit[0].end,), (hit[0],),
                          relationship_ids=_rel_ids([hit[0]]))  # fmt: skip
        lines.append("Cevap: hayır — kayıtlara göre: " + ", ".join(g.name(e) for e in ends))
    if len(ends) == 1:
        if q.check is None:
            lines.append(f"Cevap: {g.name(ends[0])}")
        lines.append(f"Dayanak: {path_text(g, complete[0])}")
        status: Status = "unique"
    else:
        if q.check is None:
            lines.append(f"Cevap: {len(ends)} kayıt var:")
        for p in complete[:MAX_LISTED]:
            lines.append(f"- {g.name(p.end)} — dayanak: {path_text(g, p)}")
        status = "several"
    return Answer(q, status, tuple(lines), tuple(ends), tuple(complete),
                  relationship_ids=_rel_ids(complete))  # fmt: skip


def _answer_path(conn: Connection, q: Query, a: str, b: str) -> Answer:
    g = _Graph(conn)
    found = paths_between(conn, a, b)
    na, nb = g.name(a), g.name(b)
    if not found:
        line = (f"{na} ile {nb} arasında kayıtlı bir bağlantı yok (en fazla {MAX_HOPS} adım "
                "arandı). Bağlantı uydurma.")  # fmt: skip
        return Answer(q, "none", (line,))
    lines = [f"{na} ile {nb} arasındaki kayıtlı bağlantılar (kısadan uzuna):"]
    lines += [f"- {path_text(g, p)}" for p in found[:MAX_LISTED]]
    if len(found) > MAX_LISTED:
        lines.append(f"(ve {len(found) - MAX_LISTED} yol daha)")
    status: Status = "unique" if len(found) == 1 else "several"
    return Answer(q, status, tuple(lines), (b,), tuple(found), relationship_ids=_rel_ids(found))


_CATEGORY_NAMES = {"family": "Aile", "social": "Sosyal", "work": "İş", "organization": "Kurum",
                   "project": "Proje", "place": "Yer", "event": "Olay"}  # fmt: skip


def _neighbour_lines(
    conn: Connection, eid: str, cats: Sequence[str] | None
) -> tuple[list[str], list[Hop]]:
    g = _Graph(conn)
    current = neighbours(conn, eid, categories=cats)
    past = neighbours(conn, eid, categories=cats, statuses=("ended",))
    groups: dict[str, list[str]] = {}
    for h in current:
        cat = relations.TYPES[h.rel.type].category
        groups.setdefault(_CATEGORY_NAMES[cat], []).append(hop_text(g, h))
    lines = [f"{name}: {'; '.join(items)}" for name, items in groups.items()]
    if past:
        lines.append("Geçmişte: " + "; ".join(hop_text(g, h) for h in past[:MAX_LISTED]))
    return lines, [*current, *past]


def _answer_neighbours(conn: Connection, q: Query, eid: str) -> Answer:
    g = _Graph(conn)
    lines, hops = _neighbour_lines(conn, eid, q.categories)
    scope = "aile ilişkileri" if q.categories == _FAMILY else "kayıtlı ilişkileri"
    head = f"{relations.genitive(g.name(eid))} {scope}:"
    if not lines:
        return Answer(q, "none", (f"{head} kayıt yok. Tahmin etme.",))
    rels = tuple(dict.fromkeys(h.rel.id for h in hops))
    ends = tuple(dict.fromkeys(h.to for h in hops))
    return Answer(q, "several", (head, *lines), ends, relationship_ids=rels)


def _answer_who(conn: Connection, q: Query, eid: str) -> Answer:
    g = _Graph(conn)
    lines, hops = _neighbour_lines(conn, eid, None)
    out = [f"{g.name(eid)} hakkındaki kayıtlı ilişkiler:", *lines]
    rels = [h.rel.id for h in hops]
    if not any(h.to == USER_ID for h in hops):
        found = paths_between(conn, USER_ID, eid)
        if found:
            out.append("Kullanıcıyla bağlantısı: " + path_text(g, found[0]))
            rels += [h.rel.id for h in found[0].hops]
    if len(out) == 1:
        line = (f"{g.name(eid)} için kayıtlı bir ilişki yok (hassas ilişkiler yalnızca açıkça "
                "sorulursa gösterilir).")  # fmt: skip
        return Answer(q, "none", (line,))
    return Answer(q, "several", tuple(out), (eid,), relationship_ids=tuple(dict.fromkeys(rels)))


def ask(conn: Connection, question: str) -> Answer | None:
    """Parse and answer in one call (None: not a relationship question)."""
    q = parse(conn, question)
    return None if q is None else answer(conn, q)
