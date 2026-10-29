"""The reply's output guards, in one stream: the model's text → the disclosure guard (internal
layers, :mod:`lazis.conversation.disclosure`) → the claim guard (memory claims,
:mod:`lazis.memory.claims`) → the user, the stored message and the voice. Each guard releases
only text it has decided on, so what the last one released is what was shown and is what is
stored.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from lazis.conversation import disclosure
from lazis.memory import claims


@dataclass
class ReplyGuard:
    policy: claims.Policy
    asks_instructions: bool = False  # :func:`disclosure.asks_instructions` of the user's message
    disclosure: disclosure.DisclosureGuard = field(init=False)
    claims: claims.ClaimGuard = field(init=False)

    def __post_init__(self) -> None:
        ctx = disclosure.Context(asks=self.asks_instructions)
        self.disclosure = disclosure.DisclosureGuard(ctx=ctx)
        self.claims = claims.ClaimGuard(self.policy)

    @property
    def released(self) -> str:
        return self.claims.released

    @property
    def rewrites(self) -> list[claims.Rewrite]:
        return self.claims.rewrites

    @property
    def internal_removed(self) -> int:
        return self.disclosure.removed

    def feed(self, chunk: str) -> str:
        # The disclosure guard releases whole words: the claim guard need not hold another.
        return self.claims.feed(self.disclosure.feed(chunk), whole_words=True)

    def finish(self) -> str:
        return self.claims.feed(self.disclosure.finish()) + self.claims.finish()


def check(text: str, policy: claims.Policy, *, asks_instructions: bool = False) -> str:
    """The whole reply at once (the same result as streaming it)."""
    guard = ReplyGuard(policy, asks_instructions)
    return guard.feed(text) + guard.finish()
