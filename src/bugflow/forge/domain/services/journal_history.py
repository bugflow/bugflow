"""The interfaces for the few things this context reads back from the
journal.

Writing to the journal goes through the shared ``RecordingService``.
Reading it back is not part of that interface, so the questions this
context asks are declared here, and an application supplies something
that answers them.
"""

from datetime import datetime
from typing import Protocol

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class PullRequestJournalService(Protocol):
    def events_for_pull_request(
        self, ref: PullRequestRef, event_type: str
    ) -> list[JournalEntry]:
        """Every entry of that type recorded for the pull request, oldest
        first."""
        ...


class JournalRepositoriesService(Protocol):
    """Answers a question about repositories, where the others here are
    about one pull request. Used when reconciling webhooks."""

    def repositories_with(self, event_type: str) -> list[tuple[str, str]]:
        """Every (forge, repository) pair the journal has an entry of
        that type for."""
        ...


class DeliveryJournalService(RecordingService, Protocol):
    """What receiving a delivery needs from the journal: writing entries,
    and one question."""

    def received_since(self, ref: PullRequestRef, since: datetime) -> bool:
        """Whether a delivery for the pull request was received at or
        after ``since``."""
        ...
