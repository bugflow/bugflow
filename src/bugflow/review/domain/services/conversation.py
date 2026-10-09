"""The interface for reading a pull request's conversation after it has
closed.

Reactions to a comment are read once, when the pull request closes. By
then they will not change.
"""

from typing import Protocol

from bugflow.review.domain.models.conversation import Closing, Reaction
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ConversationService(Protocol):
    def reactions(
        self, ref: PullRequestRef, comment_id: int
    ) -> tuple[Reaction, ...]:
        """Return the reactions to one comment on the pull request."""
        ...

    def state(self, ref: PullRequestRef) -> Closing:
        """Return how the pull request closed."""
        ...
