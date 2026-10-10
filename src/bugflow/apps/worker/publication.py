"""An adapter from the review context's publication interface to a forge.

``add_comment`` and ``set_labels`` pass straight through.
``set_commit_status`` turns the forge's ``ForgeRejectedError`` into the
review context's ``PublicationRejectedError``.
"""

from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.domain.services.forge import ForgeService
from bugflow.review.domain.errors import PublicationRejectedError
from bugflow.review.domain.services.publication import CommitState
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ForgePublication:
    """Implements the review context's ``PublicationService`` by writing
    to a forge."""

    def __init__(self, forge: ForgeService) -> None:
        self._forge = forge

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        return self._forge.add_comment(ref, marker, body)

    def set_labels(
        self,
        ref: PullRequestRef,
        add: frozenset[str],
        remove: frozenset[str],
    ) -> None:
        self._forge.set_labels(ref, add, remove)

    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: CommitState,
        description: str,
    ) -> None:
        try:
            self._forge.set_commit_status(
                ref, sha, context, state, description
            )
        except ForgeRejectedError as exc:
            raise PublicationRejectedError(str(exc)) from exc
