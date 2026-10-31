"""The reply's output guards, in one stream: the model's text → the disclosure guard (internal
layers, :mod:`lazis.conversation.disclosure`) → the people guard (unsettled namesakes and
forgotten things, :mod:`lazis.conversation.people`) → the claim guard (memory claims,
:mod:`lazis.memory.claims`) → the address guard (the user's "sen" preference,
:mod:`lazis.personality.address`) → the user, the stored message and the voice. Each guard releases
only text it has decided on, so what the last one released is what was shown and is what is
stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lazis.conversation import disclosure
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
    disclosure: disclosure.DisclosureGuard = field(init=False)
    people: PeopleGuard = field(init=False)
    claims: claims.ClaimGuard = field(init=False)
    _address: AddressGuard | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        ctx = disclosure.Context(asks=self.asks_instructions)
        self.disclosure = disclosure.DisclosureGuard(ctx=ctx)
        self.people = PeopleGuard(ctx=self.people_ctx)
        self.claims = claims.ClaimGuard(self.policy)
        self._address = AddressGuard() if self.address == "sen" else None

    @property
    def released(self) -> str:
        return self._address.released if self._address is not None else self.claims.released

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

    def feed(self, chunk: str) -> str:
        # The disclosure guard releases whole words (the people guard whole sentences): the
        # claim guard need not hold another.
        out = self.claims.feed(self.people.feed(self.disclosure.feed(chunk)), whole_words=True)
        return self._address.feed(out) if self._address is not None else out

    def finish(self) -> str:
        tail = self.people.feed(self.disclosure.finish()) + self.people.finish()
        out = self.claims.feed(tail) + self.claims.finish()
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
) -> str:
    """The whole reply at once (the same result as streaming it)."""
    guard = ReplyGuard(policy, asks_instructions, people_ctx or PeopleContext(), address)
    return guard.feed(text) + guard.finish()
