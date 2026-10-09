"""The interface to a forge, for work on one pull request."""

from typing import Literal, Protocol

from bugflow.forge.domain.models.pull_request import PullRequestSnapshot
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

#: The state of a commit status. These are the only two this server
#: sets.
CommitState = Literal["success", "failure"]


class ForgeService(Protocol):
    """Reads a pull request from a forge and writes back to it.

    Every method may raise ``ForgeError`` or one of its subclasses.
    """

    def fetch_snapshot(self, ref: PullRequestRef) -> PullRequestSnapshot:
        """Read the pull request and return a snapshot of it."""
        ...

    def is_open(self, ref: PullRequestRef) -> bool:
        """Whether the pull request is still open.

        The forge is asked directly because the delivery that says a pull
        request closed can be missed: it may arrive while the server is
        down, or not be sent at all. Something waiting only for that
        delivery could wait for ever.
        """
        ...

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        """Add a comment to the pull request, unless a comment containing
        ``marker`` is already there. Returns the comment's id.

        An existing comment is never edited. So calling this twice, for
        example after a lost response, adds one comment and changes
        nothing. A pull request's comments are a record of what was said
        and in what order; this server only adds to it.
        """
        ...

    def set_labels(
        self,
        ref: PullRequestRef,
        add: frozenset[str],
        remove: frozenset[str],
    ) -> None:
        """Add and remove labels on the pull request. Other labels are
        left alone. Removing a label that is not there is not an
        error."""
        ...

    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: CommitState,
        description: str,
    ) -> None:
        """Set the status of commit ``sha`` under the name ``context``,
        replacing any earlier status of that name.

        A repository's branch protection can require a named status to
        be "success" before merging. Setting a status does not make it
        required.
        """
        ...
