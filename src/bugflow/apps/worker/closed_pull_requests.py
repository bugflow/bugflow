"""An adapter from the work context's feed of closed pull requests to a
forge.

A forge answers with a page in its own types. The work context reads
the same page in its types. Each field is carried across as it is.
"""

from typing import Protocol

from bugflow.forge.domain.models.polling import PullRequestPage
from bugflow.work.domain.models.backfill import BackfillCandidate, BackfillPage


class ForgeFeed(Protocol):
    """What a forge adapter offers: a page in the forge context's
    types."""

    def closed_pull_requests(
        self, owner: str, repo: str, page: int
    ) -> PullRequestPage: ...


class ForgeClosedPullRequests:
    """Implements the work context's ``ClosedPullRequestFeedRepository``
    by asking a forge."""

    def __init__(self, feed: ForgeFeed) -> None:
        self._feed = feed

    def closed_pull_requests(
        self, owner: str, repo: str, page: int
    ) -> BackfillPage:
        forge_page = self._feed.closed_pull_requests(owner, repo, page)
        return BackfillPage(
            pulls=tuple(
                BackfillCandidate(ref=pull.ref, head_sha=pull.head_sha)
                for pull in forge_page.pulls
            ),
            last=forge_page.last,
        )
