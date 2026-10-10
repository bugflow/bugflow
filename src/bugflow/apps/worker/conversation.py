"""An adapter from the review context's conversation interface to a forge.

The forge says what its API says. The review context reads the same
facts in its own types. Nothing is decided here: each field is carried
across as it is.
"""

from typing import Protocol

from bugflow.forge.domain.services.conversation import (
    ConversationService as ForgeConversationService,
)
from bugflow.forge.domain.services.forge import ForgeService
from bugflow.review.domain.models.conversation import Closing, Reaction
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ConversingForge(ForgeService, ForgeConversationService, Protocol):
    """A forge that also says what a closed conversation was."""


class ForgeConversation:
    """Implements the review context's ``ConversationService`` by asking
    a forge."""

    def __init__(self, forge: ForgeConversationService) -> None:
        self._forge = forge

    def reactions(
        self, ref: PullRequestRef, comment_id: int
    ) -> tuple[Reaction, ...]:
        return tuple(
            Reaction(content=r.content, login=r.login, reacted_at=r.reacted_at)
            for r in self._forge.reactions(ref, comment_id)
        )

    def state(self, ref: PullRequestRef) -> Closing:
        state = self._forge.state(ref)
        return Closing(merged=state.merged, head_sha=state.head_sha)
