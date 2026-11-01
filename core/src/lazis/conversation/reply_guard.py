"""The reply's output guards, in one stream: the model's text → the disclosure guard (internal
layers, :mod:`lazis.conversation.disclosure`) → the people guard (unsettled namesakes and
forgotten things, :mod:`lazis.conversation.people`) → the claim guard (memory claims,
:mod:`lazis.memory.claims`) → the DOI guard (identifiers with no source,
:mod:`lazis.conversation.citations`) → the address guard (the user's "sen" preference,
:mod:`lazis.personality.address`) → the user, the stored message and the voice. Each guard releases
only text it has decided on, so what the last one released is what was shown and is what is
stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lazis.conversation import citations, disclosure
from lazis.conversation.people import Context as PeopleContext
from lazis.conversation.people import PeopleGuard
from lazis.memory import claims
from lazis.personality.address import AddressGuard


@dataclass
class ReplyGuard:
    policy: claims.Policy
    asks_instructions: bool = False  # :func:`disclosure.asks_instructions` of the user's message
    people_ctx: PeopleContext = field(default_factory=PeopleContext)
    address: str = "siz"  # layer 2: "sen" turns the reply's "siz" forms into "sen"
    dois: frozenset[str] = frozenset()  # DOIs with a source (:func:`citations.grounded`)
    doi_fiction: bool = False  # :func:`citations.asks_fiction` of the user's message
    dois_pending: bool = False  # more sources follow (:meth:`add_dois`)
    disclosure: disclosure.DisclosureGuard = field(init=False)
    people: PeopleGuard = field(init=False)
    claims: claims.ClaimGuard = field(init=False)
    doi: citations.DoiGuard = field(init=False)
    _address: AddressGuard | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        ctx = disclosure.Context(asks=self.asks_instructions)
        self.disclosure = disclosure.DisclosureGuard(ctx=ctx)
        self.people = PeopleGuard(ctx=self.people_ctx)
        self.claims = claims.ClaimGuard(self.policy)
        self.doi = citations.DoiGuard(
            sources=self.dois, fiction=self.doi_fiction, complete=not self.dois_pending
        )
        self._address = AddressGuard() if self.address == "sen" else None

    @property
    def released(self) -> str:
        return self._address.released if self._address is not None else self.doi.released

    @property
    def address_fixed(self) -> int:
        return len(self._address.changed) if self._address is not None else 0

    @property
    def rewrites(self) -> list[claims.Rewrite]:
        return self.claims.rewrites

    @property
    def internal_removed(self) -> int:
        return self.disclosure.removed

    @property
    def people_removed(self) -> dict[str, int]:
        return self.people.removed

    def add_dois(self, more: frozenset[str]) -> None:
        self.doi.add(more)

    def feed(self, chunk: str) -> str:
        # The disclosure guard releases whole words (the people guard whole sentences): the
        # claim guard need not hold another.
        out = self.claims.feed(self.people.feed(self.disclosure.feed(chunk)), whole_words=True)
        out = self.doi.feed(out)
        return self._address.feed(out) if self._address is not None else out

    def finish(self) -> str:
        tail = self.people.feed(self.disclosure.finish()) + self.people.finish()
        out = self.claims.feed(tail) + self.claims.finish()
        out = self.doi.feed(out) + self.doi.finish()
        if self._address is None:
            return out
        return self._address.feed(out) + self._address.finish()


def check(
    text: str,
    policy: claims.Policy,
    *,
    asks_instructions: bool = False,
    people_ctx: PeopleContext | None = None,
    address: str = "siz",
    dois: frozenset[str] = frozenset(),
    doi_fiction: bool = False,
) -> str:
    """The whole reply at once (the same result as streaming it)."""
    guard = ReplyGuard(
        policy, asks_instructions, people_ctx or PeopleContext(), address, dois, doi_fiction
    )
    return guard.feed(text) + guard.finish()
