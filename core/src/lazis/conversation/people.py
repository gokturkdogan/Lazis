"""The reply never speaks of an unsettled person as one of them, nor of what the user asked to
forget (Phase 10A, ADR-0021).

Recall tells the model which namesakes the message does not settle and which topics were
forgotten; the model still answers from the chat history or by guessing ("Ahmet'in kardeşi
Mehmet'tir. Ancak … hangi Ahmet?", "Mehmet bu kişilerden hangisinin kuzeniydi?" after the
relationship was forgotten). This guard enforces it on the text, with no model call:

* a sentence certain about an unsettled person (:func:`lazis.memory.unsettled.certain`) is
  dropped; if the reply is then left without a question, it asks one ("Hangi Ahmet olduğunu
  belirtir misiniz?");
* a sentence that speaks of a forgotten relationship or value
  (:meth:`lazis.memory.forgotten.Index.speaks_of`) is dropped; a reply left with nothing says
  there is no record.

It works on whole sentences, and only in a turn that has something to check: otherwise the
text passes through untouched. Released text is final, so what was shown is what is stored
(it sits between the disclosure guard and the claim guard, :mod:`reply_guard`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lazis.memory import forgotten, text, unsettled
from lazis.storage.driver import Connection

NO_RECORD = "Bu konuda kayıtlı bir bilgim yok."
MAX_HOLD = 400  # characters held without a sentence end before deciding at a space
_END = re.compile(r"[.!?;…]+[\"'»”)]*(?=\s|$)|\n")
# The first words of a sentence that only make sense after the one dropped before it.
_LEAD = re.compile(
    r"^(?:ancak|fakat|ama|yine de|bununla birlikte|öte yandan|ayrıca|bu arada|"
    r"ne var ki|lakin)\s*,?\s+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Context:
    message: str = ""
    unsettled: tuple[unsettled.Unsettled, ...] = ()
    forgotten: forgotten.Index = field(default_factory=forgotten.Index)

    @property
    def active(self) -> bool:
        return bool(self.unsettled) or not self.forgotten.empty


def build(
    conn: Connection, unsettled_ids: tuple[str, ...], message: str, *, asking: bool
) -> Context:
    """This turn's checks: the unsettled people recall found in the message, and — when the
    user asks something or names a stored person — what was forgotten."""
    people = unsettled.load(conn, unsettled_ids) if unsettled_ids else ()
    index = forgotten.Index()
    if forgotten.has_any(conn):
        index = forgotten.load(conn, message=message)
        if not (asking or index.named(text.words(message))):
            index = forgotten.Index()
    return Context(message, people, index)


@dataclass
class PeopleGuard:
    ctx: Context = field(default_factory=Context)
    released: str = ""
    pending: str = ""
    removed: dict[str, int] = field(default_factory=dict[str, int])
    _after_drop: bool = False
    _asked: str | None = None  # the name to ask about, once a sentence about it was dropped

    def feed(self, chunk: str) -> str:
        if not self.ctx.active:
            self.released += chunk
            return chunk
        self.pending += chunk
        return self._release(final=False)

    def finish(self) -> str:
        out = self._release(final=True)
        piece = ""
        if self._asked is not None and "?" not in self.released:
            piece = f"Hangi {self._asked} olduğunu belirtir misiniz?"
        elif self.removed and not self.released.strip():
            piece = NO_RECORD
        if piece:
            if self.released.strip() and not self.released.endswith((" ", "\n")):
                piece = " " + piece
            self.released += piece
            out += piece
        return out

    @property
    def count(self) -> int:
        return sum(self.removed.values())

    def _release(self, *, final: bool) -> str:
        out = ""
        while self.pending:
            m = _END.search(self.pending)
            if m is not None:
                end = m.end()
            elif final:
                end = len(self.pending)
            elif len(self.pending) >= MAX_HOLD:
                end = self.pending.rfind(" ", 0, MAX_HOLD) + 1 or MAX_HOLD
            else:
                break
            sentence, self.pending = self.pending[:end], self.pending[end:]
            out += self._decide(sentence)
        return out

    def _decide(self, sentence: str) -> str:
        if not sentence.strip():
            return self._add(sentence)
        kind: str | None = None
        for u in self.ctx.unsettled:
            k = unsettled.certain(sentence, u, self.ctx.message)
            if k is not None:
                kind = f"unsettled_{k}"
                self._asked = self._asked or u.name
                break
        if kind is None:
            f = self.ctx.forgotten.speaks_of(sentence)
            kind = None if f is None else f"forgotten_{f}"
        if kind is None:
            piece = sentence
            if self._after_drop:
                body = sentence.lstrip()
                lead = _LEAD.match(body)
                if lead is not None and len(body) > lead.end():
                    rest = body[lead.end() :]
                    piece = sentence[: len(sentence) - len(body)] + rest[0].upper() + rest[1:]
            self._after_drop = False
            return self._add(piece)
        self.removed[kind] = self.removed.get(kind, 0) + 1
        self._after_drop = True
        if sentence.endswith("\n") and self.released and not self.released.endswith("\n"):
            return self._add("\n")
        return ""

    def _add(self, piece: str) -> str:
        if not self.released.strip():
            piece = piece.lstrip()  # a reply whose first sentence was dropped
        elif self.released.endswith("\n"):
            piece = piece.lstrip(" ")
        self.released += piece
        return piece
