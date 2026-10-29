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
    disclosure: disclosure.DisclosureGuard = field(default_factory=disclosure.DisclosureGuard)
    claims: claims.ClaimGuard = field(init=False)

    def __post_init__(self) -> None:
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


def check(text: str, policy: claims.Policy) -> str:
    """The whole reply at once (the same result as streaming it)."""
    guard = ReplyGuard(policy)
    return guard.feed(text) + guard.finish()
