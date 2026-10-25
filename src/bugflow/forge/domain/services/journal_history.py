"""The interfaces for the few things this context reads back from the
journal.

Writing to the journal goes through the shared ``RecordingService``.
Reading it back is not part of that interface, so the questions this
context asks are declared here, and an application supplies something
that answers them.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from bugflow.forge.domain.models.judgement import RecordedJudgement
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class PullRequestJournalService(Protocol):
    def events_for_pull_request(
        self, ref: PullRequestRef, event_type: str
    ) -> Sequence[JournalEntry]:
        """Every entry of that type recorded for the pull request, oldest
        first."""
        ...

    def judgements_for_pull_request(
        self, ref: PullRequestRef
    ) -> Sequence[RecordedJudgement]:
        """Every ``judge.invoked`` fact recorded for the pull request,
        oldest first, read from its table (ADR 007)."""
        ...


class JournalRepositoriesService(Protocol):
    """Answers which repositories the webhook reconciler remembers."""

    def repositories_with(self, event_type: str) -> list[tuple[str, str]]:
        """Every (forge, repository) pair with that event type."""
        ...


class DeliveryJournalService(RecordingService, Protocol):
    """What receiving a delivery needs from the journal: writing entries,
    and one question."""

    def received_since(
        self,
        ref: PullRequestRef,
        since: datetime,
        *,
        origin: str | None = None,
    ) -> bool:
        """Whether a delivery for the pull request was received at or
        after ``since``."""
        ...


class OriginJournalRepositoriesService(Protocol):
    """Lists only repositories explicitly retained for one endpoint."""

    def repositories_with_origin(
        self, event_type: str, origin_endpoint: str
    ) -> list[tuple[str, str]]:
        """Return records whose origin host and path match the journal row."""
        ...
