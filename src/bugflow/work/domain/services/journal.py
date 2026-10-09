"""The interface for the questions this context asks of the journal.

Writing to the journal is the same for every context, and its interface
is ``bugflow.shared.domain.services.recording.RecordingService``. What a
context needs to read differs, so each context has a reading interface
of its own. This is this context's.
"""

from typing import Protocol

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.work.domain.models.journal import DispatchedRun


class JournalService(Protocol):
    def events_for_pull_request(
        self, ref: PullRequestRef, event_type: str
    ) -> list[JournalEntry]:
        """Return every entry of this type recorded for the pull
        request, oldest first."""
        ...

    def dispatched_run(
        self, runner: str, remote_id: str
    ) -> DispatchedRun | None:
        """Return the workflow run and agent that a runner's piece of
        work was dispatched for.

        Returns None if the journal records no such dispatch: the work
        is unknown, or this server did not start it.
        """
        ...
