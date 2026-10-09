"""The interface for writing to a pull request on the forge."""

from typing import Literal, Protocol

from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

#: The state of a commit status. Only these two are set.
CommitState = Literal["success", "failure"]


class PublicationService(Protocol):
    """Each method raises ``PublicationRejectedError`` if the forge
    refuses the write for good."""

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        """Add a comment, unless the pull request already has a comment
        that contains ``marker``. Returns the comment's id.

        A comment that is already there is not edited. So calling this
        again, after an answer from the forge was lost, adds nothing.
        """
        ...

    def set_labels(
        self,
        ref: PullRequestRef,
        add: frozenset[str],
        remove: frozenset[str],
    ) -> None:
        """Add and remove labels. Other labels are left alone."""
        ...

    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: CommitState,
        description: str,
    ) -> None:
        """Set one commit status on commit ``sha``. ``context`` is the
        status's name, and ``description`` the short text beside it."""
        ...
