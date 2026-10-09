"""The interface for reading a pull request's discussion after it has
closed.

GitHub sends no delivery when someone reacts to a comment. So reactions
are read once, when the pull request closes.

This is separate from ``ForgeService`` so that the many implementations
of ``ForgeService`` used in tests do not each have to provide it.
"""

from typing import Protocol

from bugflow.forge.domain.values.conversation import (
    PullRequestState,
    Reaction,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ConversationService(Protocol):
    def reactions(
        self, ref: PullRequestRef, comment_id: int
    ) -> tuple[Reaction, ...]:
        """Every reaction on the comment, in the forge's order."""
        ...

    def state(self, ref: PullRequestRef) -> PullRequestState:
        """Whether the pull request was merged, and its last commit."""
        ...
