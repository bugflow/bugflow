"""Keep reused review evidence within the current run's repository origin."""

from collections.abc import Sequence
from uuid import UUID

from bugflow.review.domain.facts import ACTION_TAKEN
from bugflow.review.domain.models.observation import Observation
from bugflow.review.domain.services.journal import JournalService
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.models.journal_provenance import resolve_origin
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.dismissal import Dismissal
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    RepositoryAssociationUnresolvedError,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin


def for_run(
    journal: JournalService, ref: PullRequestRef, run: Correlation
) -> JournalService:
    entries = [
        entry
        for entry in journal.entries_for_run(run)
        if (entry.forge, entry.repo, entry.pr_number)
        == (ref.forge, f"{ref.owner}/{ref.repo}", ref.number)
    ]
    origins = {entry.origin for entry in entries}
    if not origins or origins == {None}:
        return journal
    if None in origins:
        raise RepositoryAssociationUnresolvedError(
            "current run contains unresolved journal entries"
        )
    if len(origins) != 1:
        raise AssociationConflictError(
            "current run contains different origins"
        )
    origin = next(iter(origins))
    assert origin is not None
    return OriginJournal(journal, ref, origin)


def for_origin(
    journal: JournalService,
    ref: PullRequestRef,
    run: Correlation,
    origin: str | None,
) -> JournalService:
    """Check an observed source before reusing historical evidence."""
    repo = f"{ref.owner}/{ref.repo}"
    if origin is not None:
        RepositoryOrigin(origin)
        if origin.split("/", 1)[1] != repo:
            raise ValueError("observed origin does not match repository")
    if not run.workflow_id or not run.run_id:
        raise ValueError("observed origin requires a workflow run")
    retained = (
        entry.origin
        for entry in journal.entries_for_run(run)
        if (entry.forge, entry.repo, entry.pr_number)
        == (ref.forge, repo, ref.number)
    )
    resolve_origin(
        (run.workflow_id, run.run_id, ref.forge, repo, ref.number),
        (origin,),
        retained,
    )
    return journal if origin is None else OriginJournal(journal, ref, origin)


class OriginJournal:
    def __init__(
        self, journal: JournalService, ref: PullRequestRef, origin: str
    ) -> None:
        self._journal = journal
        self._origin = origin
        self._ref = ref

    def append(self, entries: Sequence[JournalEntry]) -> None:
        self._journal.append(entries)

    def has_event(self, event_id: UUID) -> bool:
        return self._journal.has_event(event_id)

    def _matching(self, entries: list[JournalEntry]) -> list[JournalEntry]:
        return [entry for entry in entries if entry.origin == self._origin]

    def entries_for_run(self, correlation: Correlation) -> list[JournalEntry]:
        return [
            entry
            for entry in self._matching(
                self._journal.entries_for_run(correlation)
            )
            if entry.forge == self._ref.forge
            and entry.pr_number == self._ref.number
        ]

    def events_for_pull_request(
        self, ref: PullRequestRef, event_type: str
    ) -> list[JournalEntry]:
        return self._matching(
            self._journal.events_for_pull_request(ref, event_type)
        )

    def events_for_repository(
        self, forge: str, repo: str, event_type: str
    ) -> list[JournalEntry]:
        return self._matching(
            self._journal.events_for_repository(forge, repo, event_type)
        )

    def observations_for_pull_request(
        self, ref: PullRequestRef, origin: str | None = None
    ) -> list[Observation]:
        return self._journal.observations_for_pull_request(ref, self._origin)

    def dismissals_for_pull_request(
        self, ref: PullRequestRef, origin: str | None = None
    ) -> list[Dismissal]:
        return self._journal.dismissals_for_pull_request(ref, self._origin)

    def latest_acted_run(
        self, ref: PullRequestRef, excluding: Correlation
    ) -> Correlation | None:
        # The underlying query orders by occurrence and recording time.
        for entry in reversed(self.events_for_pull_request(ref, ACTION_TAKEN)):
            run = Correlation(
                workflow_id=entry.workflow_id, run_id=entry.run_id
            )
            if run != excluding:
                return run
        return None
