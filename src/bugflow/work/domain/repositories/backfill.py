"""The interface for listing a repository's closed pull requests."""

from typing import Protocol

from bugflow.shared.domain.repositories.base import BaseRepository
from bugflow.work.domain.models.backfill import BackfillPage


class ClosedPullRequestFeedRepository(BaseRepository[BackfillPage], Protocol):
    def closed_pull_requests(
        self, owner: str, repo: str, page: int
    ) -> BackfillPage:
        """Return one page of the repository's closed pull requests,
        oldest first. Pages are counted from 1.

        If the forge cannot answer, the adapter's own error is raised.
        This context does not name the errors of a forge."""
        ...
