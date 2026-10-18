"""The interface for the questions this context asks of the journal.

It includes writing, so that one object can be given for both.
"""

from typing import Protocol

from bugflow.review.domain.models.history import (
    HistoryLimits,
    HistoryScope,
    StoredReviewEvent,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class HistoryService(Protocol):
    def entries_for_history(
        self, scope: HistoryScope, limits: HistoryLimits
    ) -> tuple[StoredReviewEvent, ...]:
        """Read one consistent, bounded set of repository-scoped facts.

        Refuse the entire request if a limit is exceeded. Order by event
        time, recording time and event id. No linked content is opened.
        """
        ...


class JournalService(RecordingService, Protocol):
    def entries_for_run(self, correlation: Correlation) -> list[JournalEntry]:
        """Return every entry one workflow run recorded, oldest first."""
        ...

    def latest_acted_run(
        self, ref: PullRequestRef, excluding: Correlation
    ) -> Correlation | None:
        """Return the most recent workflow run, other than
        ``excluding``, that wrote something to the pull request. That
        is the last evaluation that got as far as publishing. None if
        there is none."""
        ...

    def events_for_pull_request(
        self, ref: PullRequestRef, event_type: str
    ) -> list[JournalEntry]:
        """Return every entry of this type recorded for the pull
        request, oldest first."""
        ...

    def events_for_repository(
        self, forge: str, repo: str, event_type: str
    ) -> list[JournalEntry]:
        """Return every entry of this type recorded for the repository,
        oldest first, whether or not it belongs to a pull request. A
        stocktake reads these."""
        ...
