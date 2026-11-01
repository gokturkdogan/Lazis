"""The user's communication preferences: stored, learned, explained (Phase 10B, ADR-0022).

Layer 2 of the persona (``lazis.personality.preferences`` reads the words and renders the
text; this module keeps the values and decides when they change).

* **Explicit** — a standing instruction ("Daha kısa cevap ver", "Bana siz deme") takes effect
  in the same turn and stays until the user changes or removes it. No signal threshold.
* **Implicit** — a per-reply request or reaction ("Kısaca anlat", "Çok uzun oldu") is one
  *signal* for one dimension and direction. A learned step needs at least
  :data:`~lazis.memory.signals.MIN_SIGNALS` independent statements in at least
  :data:`~lazis.memory.signals.MIN_SESSIONS` sessions since the dimension last changed, with
  at least :data:`CONSISTENCY` of them pointing the same way; it moves the value by one level
  (0.1) and uses those signals up. Independence is Phase 10A's: one signal per user message
  (the primary key: reprocessing never adds one), the same words once, sessions counted
  apart; only the user's own live messages are read (never an import, a memory record, or
  LAZIS's words).
* **Explicit wins**: while an explicit value is set, learning never changes that dimension.
* **Removal is final for old signals**: removing a preference resets it to LAZIS's default
  and no signal from before the removal ever counts again.
* **Refused** — a request no preference may grant ("beni hep onayla") changes nothing; it is
  recorded with its reason and the reply is told why.

Every change is a row in ``preference_changes`` (what, from what, to what, and why).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from lazis.ids import new_ulid
from lazis.memory import repository as memory_repo
from lazis.memory import signals as sig
from lazis.memory.commands import NOTICE_END, NOTICE_START
from lazis.personality import preferences as prefs
from lazis.personality.preferences import CommunicationPreferences, Dimension
from lazis.storage.driver import Connection

CONSISTENCY = 0.75  # share of the signals since the last change that point the same way

_REASONS = {
    "agree_always": "her söylediğini onaylamak",
    "never_disagree": "hiç itiraz etmemek",
    "dishonesty": "bilmediğini uydurmak ya da gerçeği gizlemek",
    "safety": "güvenlik kurallarını ya da uyarıları bırakmak",
    "identity": "kimliğini değiştirmek ya da duygu iddia etmek",
    "memory_truth": "hafıza işlemleri hakkında gerçek dışı konuşmak",
}


# A refused request stays in the history for the rest of the conversation, and the model sees
# it on every later turn ("Bilmiyorsan uydur" before a question it cannot answer): every later
# reply is told it does not apply, in the words of what it asked.
_STANDING = {
    "agree_always": "Kullanıcı yanlış bir şey söylerse nazikçe düzelt; onu onaylamak için "
    "doğruyu değiştirme.",
    "never_disagree": "Gerektiğinde nazikçe itiraz et ya da düzelt.",
    "dishonesty": "Bilmediğin ya da doğrulayamadığın bir bilgiyi, kaynağı, DOI'yi, bağlantıyı, "
    "sayıyı ya da adı uydurma; emin değilsen bunu açıkça söyle ve nereden doğrulanabileceğini "
    "belirt.",
    "safety": "Önemli güvenlik ve sağlık uyarılarını yine söyle.",
    "identity": "Adın LAZIS olarak kalır; hissetmediğin bir duyguyu iddia etme.",
    "memory_truth": "Hafızanda olan ve olmayan hakkında yalnızca gerçekte olanı söyle.",
}


def standing_note(reasons: set[str] | frozenset[str]) -> str:
    """For this request only: earlier refused requests of this conversation still do not
    apply. Empty when there are none."""
    known = [r for r in _STANDING if r in reasons]
    if not known:
        return ""
    what = ", ".join(_REASONS[r] for r in known)
    rules = [f"- {_STANDING[r]}" for r in known]
    return "\n".join([
        NOTICE_START,
        f"Kullanıcı bu konuşmada daha önce bir konuşma tarzı tercihi olmayan bir şey istedi "
        f"({what}). O istek geçerli değil ve bu yanıtta da uygulanmaz:",
        *rules,
        "Bunu her yanıtta tekrar söyleme; yalnızca öyle davran.",
        NOTICE_END,
    ])  # fmt: skip


@dataclass(frozen=True)
class Stored:
    dimension: Dimension
    explicit: str | None = None
    explicit_at: str | None = None
    learned: str | None = None
    learned_at: str | None = None
    cleared_at: str | None = None


@dataclass(frozen=True)
class Step:
    dimension: Dimension
    old: int | str | bool
    new: int | str | bool


@dataclass(frozen=True)
class Observed:
    """What one user message changed."""

    applied: tuple[Step, ...] = ()
    cleared: tuple[Dimension, ...] = ()
    refused: tuple[str, ...] = ()
    signals: int = 0  # new implicit signals recorded
    learned: tuple[Step, ...] = ()
    preferences: CommunicationPreferences = field(default_factory=CommunicationPreferences)

    def notice(self) -> str:
        """For this reply only (never stored): what changed, so the reply can say so."""
        parts: list[str] = []
        if self.applied:
            what = ", ".join(prefs.describe(s.dimension, s.new) for s in self.applied)
            parts.append(
                f"Kullanıcı konuşma tarzını değiştirdi ({what}). Bu yanıttan başlayarak uygula; "
                "sonraki konuşmalarda da geçerli. Uygulayacağını en fazla bir kısa cümleyle "
                "söyleyebilirsin; kaydetmekten ya da hafızandan söz etme."
            )
        if self.cleared:
            parts.append(
                "Kullanıcı konuşma tarzıyla ilgili tercihini kaldırdı; artık varsayılan "
                "üslubunla konuş."
            )
        if self.refused:
            what = ", ".join(_REASONS.get(r, r) for r in self.refused)
            parts.append(
                f"Kullanıcının isteğinin bir kısmı ({what}) bir konuşma tarzı tercihi değil: "
                "dürüstlük, doğruluk, güvenlik ve kimliğin değişmez. Bunu nazikçe ve kısaca "
                "söyle; tonunu yumuşatabileceğini ve kararların ona ait olduğunu belirtebilirsin. "
                "Bu konuda söz verme ya da kabul etmiş gibi yapma."
            )
        if not parts:
            return ""
        return f"{NOTICE_START}\n" + "\n".join(parts) + f"\n{NOTICE_END}"


def load(conn: Connection) -> dict[Dimension, Stored]:
    rows = conn.execute(
        "SELECT dimension, explicit_value, explicit_at, learned_value, learned_at, cleared_at"
        " FROM communication_preferences"
    ).fetchall()
    return {
        r[0]: Stored(r[0], r[1], r[2], r[3], r[4], r[5])  # type: ignore[arg-type]
        for r in rows
    }


def effective(conn: Connection, base: CommunicationPreferences) -> CommunicationPreferences:
    """Explicit value > learned value > ``base`` (config, then LAZIS's default)."""
    out = base
    for dim, row in load(conn).items():
        raw = row.explicit if row.explicit is not None else row.learned
        if raw is not None:
            out = out.with_value(dim, prefs.parse(dim, raw))
    return out


def sources(conn: Connection) -> dict[Dimension, str]:
    """Where each dimension's value comes from: explicit, learned or default."""
    stored = load(conn)
    out: dict[Dimension, str] = {}
    for dim in prefs.DIMENSIONS:
        row = stored.get(dim)
        if row is not None and row.explicit is not None:
            out[dim] = "explicit"
        elif row is not None and row.learned is not None:
            out[dim] = "learned"
        else:
            out[dim] = "default"
    return out


def _upsert(conn: Connection, dim: Dimension, now: str, **cols: str | None) -> None:
    conn.execute(
        "INSERT INTO communication_preferences (dimension, updated_at) VALUES (?, ?)"
        " ON CONFLICT(dimension) DO NOTHING",
        (dim, now),
    )
    sets = ", ".join(f"{k} = ?" for k in cols)
    conn.execute(
        f"UPDATE communication_preferences SET {sets}, updated_at = ? WHERE dimension = ?",  # noqa: S608 - fixed column names
        (*cols.values(), now, dim),
    )


def _log(
    conn: Connection,
    *,
    dim: Dimension | None,
    source: str,
    old: object,
    new: object,
    message_id: str | None,
    now: str,
    detail: Mapping[str, object] | None = None,
) -> None:
    conn.execute(
        "INSERT INTO preference_changes (id, dimension, source, old_value, new_value,"
        " message_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            new_ulid(),
            dim,
            source,
            None if old is None else prefs.dump(old),  # type: ignore[arg-type]
            None if new is None else prefs.dump(new),  # type: ignore[arg-type]
            message_id,
            json.dumps(dict(detail or {}), ensure_ascii=False, sort_keys=True),
            now,
        ),
    )


def set_explicit(
    conn: Connection,
    dim: Dimension,
    value: int | str | bool,
    *,
    base: CommunicationPreferences,
    now: str,
    message_id: str | None = None,
    source: str = "explicit",
) -> Step:
    old = effective(conn, base).get(dim)
    _upsert(conn, dim, now, explicit_value=prefs.dump(value), explicit_at=now,
            explicit_message_id=message_id)  # fmt: skip
    _log(conn, dim=dim, source=source, old=old, new=value, message_id=message_id, now=now)
    return Step(dim, old, value)


def clear(
    conn: Connection,
    dim: Dimension,
    *,
    base: CommunicationPreferences,
    now: str,
    message_id: str | None = None,
) -> None:
    """Back to LAZIS's default; every signal so far is spent."""
    old = effective(conn, base).get(dim)
    _upsert(conn, dim, now, explicit_value=None, explicit_at=None, explicit_message_id=None,
            learned_value=None, learned_at=None, cleared_at=now)  # fmt: skip
    _log(conn, dim=dim, source="cleared", old=old, new=base.get(dim), message_id=message_id,
         now=now)  # fmt: skip


def _words_mark(conn: Connection, words: str) -> str:
    key = memory_repo.fingerprint_key(conn)
    return hmac.new(key, f"style\x00{words}".encode(), hashlib.sha256).hexdigest()


def record_signal(
    conn: Connection,
    dim: Dimension,
    direction: int,
    *,
    message_id: str,
    conversation_id: str,
    words: str,
    now: str,
) -> bool:
    """False when this message already gave a signal for ``dim`` (a reprocessed message)."""
    cur = conn.execute(
        "INSERT OR IGNORE INTO preference_signals (dimension, message_id, conversation_id,"
        " direction, words, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            dim,
            message_id,
            conversation_id,
            1 if direction > 0 else -1,
            _words_mark(conn, words or message_id),
            now,
        ),
    )
    return bool(cur.rowcount)


@dataclass(frozen=True)
class Evidence:
    """The independent signals for a dimension since it last changed."""

    up: sig.Tally
    down: sig.Tally
    message_ids: tuple[str, ...]

    @property
    def direction(self) -> int:
        """+1 / -1 when one side is enough and consistent, else 0."""
        for d, t, other in ((1, self.up, self.down), (-1, self.down, self.up)):
            total = t.messages + other.messages
            if t.enough and total and t.messages / total >= CONSISTENCY:
                return d
        return 0


def evidence(conn: Connection, dim: Dimension) -> Evidence:
    row = load(conn).get(dim)
    since = max((x for x in (row.cleared_at, row.learned_at) if x), default="") if row else ""
    rows = conn.execute(
        "SELECT direction, message_id, conversation_id, words FROM preference_signals"
        " WHERE dimension = ? AND created_at > ? ORDER BY created_at",
        (dim, since),
    ).fetchall()
    found = [sig.Signal("up" if int(r[0]) > 0 else "down", str(r[1]), str(r[2]), str(r[3]))
             for r in rows]  # fmt: skip
    t = sig.tally(found)
    none = sig.Tally(0, 0)
    return Evidence(t.get("up", none), t.get("down", none), tuple(str(r[1]) for r in rows))


def learn(
    conn: Connection, dim: Dimension, *, base: CommunicationPreferences, now: str
) -> Step | None:
    """One learned step for ``dim`` if the signals since its last change allow it."""
    if dim not in prefs.LEARNABLE:
        return None
    row = load(conn).get(dim)
    if row is not None and row.explicit is not None:
        return None  # the user's own words win; signals wait
    ev = evidence(conn, dim)
    if not ev.direction:
        return None
    current = effective(conn, base).get(dim)
    new = prefs.clamp(int(current) + ev.direction * prefs.LEARNED_STEP)
    if new == current:
        return None
    _upsert(conn, dim, now, learned_value=prefs.dump(new), learned_at=now)
    t = ev.up if ev.direction > 0 else ev.down
    _log(conn, dim=dim, source="learned", old=current, new=new, message_id=None, now=now,
         detail={"signals": list(ev.message_ids), "statements": t.messages,
                 "sessions": t.sessions,
                 "against": (ev.down if ev.direction > 0 else ev.up).messages})  # fmt: skip
    return Step(dim, current, new)


def observe(
    conn: Connection,
    *,
    message_id: str,
    conversation_id: str,
    content: str,
    after_reply: bool,
    base: CommunicationPreferences,
    now: str,
) -> Observed:
    """Read one live user message for style and apply what it says (caller's transaction)."""
    r = prefs.read(content, after_reply=after_reply)
    if not r.any:
        return Observed(preferences=effective(conn, base))
    for dim in r.cleared:
        clear(conn, dim, base=base, now=now, message_id=message_id)
    applied: list[Step] = []
    for change in r.explicit:
        value = prefs.apply(effective(conn, base), change)
        applied.append(set_explicit(conn, change.dim, value, base=base, now=now,
                                    message_id=message_id))  # fmt: skip
    for reason in r.refused:
        _log(conn, dim=None, source="refused", old=None, new=None, message_id=message_id,
             now=now, detail={"reason": reason})  # fmt: skip
    recorded = 0
    learned: list[Step] = []
    for s in r.signals:
        if record_signal(conn, s.dim, int(s.op[1]), message_id=message_id,
                         conversation_id=conversation_id, words=r.words, now=now):  # fmt: skip
            recorded += 1
            step = learn(conn, s.dim, base=base, now=now)
            if step is not None:
                learned.append(step)
    return Observed(tuple(applied), r.cleared, r.refused, recorded, tuple(learned),
                    effective(conn, base))  # fmt: skip


def history(conn: Connection, limit: int = 50) -> list[dict[str, object]]:
    rows = conn.execute(
        "SELECT dimension, source, old_value, new_value, message_id, detail, created_at"
        " FROM preference_changes ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [
        {"dimension": r[0], "source": r[1], "old_value": r[2], "new_value": r[3],
         "message_id": r[4], "detail": json.loads(r[5] or "{}"), "created_at": r[6]}
        for r in rows
    ]  # fmt: skip
