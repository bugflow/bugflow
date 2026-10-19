"""Select and record repository-wide evidence within one origin."""

from collections.abc import Sequence
from dataclasses import replace

from bugflow.review.domain.services.journal import JournalService
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.models.journal_provenance import (
    JournalScope,
    resolve_origin,
    scope_of,
)
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    RepositoryAssociationUnresolvedError,
)
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin


def _origins(journal: JournalService, scope: JournalScope) -> set[str | None]:
    run = Correlation(workflow_id=scope[0], run_id=scope[1])
    return {
        entry.origin
        for entry in journal.entries_for_run(run)
        if scope_of(entry) == scope
    }


class RepositoryJournal:
    def __init__(
        self, journal: JournalService, scope: JournalScope, origin: str | None
    ) -> None:
        if not scope[0] or not scope[1]:
            raise ValueError("repository provenance requires a workflow run")
        if origin is not None:
            RepositoryOrigin(origin)
            if origin.split("/", 1)[1] != scope[3]:
                raise ValueError("repository origin does not match its path")
        resolve_origin(scope, (origin,), _origins(journal, scope))
        self._journal = journal
        self._scope = scope
        self.origin = origin

    def append(self, entries: Sequence[JournalEntry]) -> None:
        for entry in entries:
            if scope_of(entry) != self._scope:
                raise AssociationConflictError(
                    "entry belongs to another repository run"
                )
            if (
                entry.origin is not None or entry.origin_asserted
            ) and entry.origin != self.origin:
                raise AssociationConflictError(
                    "entry asserts another repository origin"
                )
        self._journal.append(
            [
                replace(entry, origin=self.origin, origin_asserted=True)
                for entry in entries
            ]
        )

    def events(self, event_type: str) -> list[JournalEntry]:
        return [
            entry
            for entry in self._journal.events_for_repository(
                self._scope[2], self._scope[3], event_type
            )
            if self.origin is None or entry.origin == self.origin
        ]


def for_repository_origin(
    journal: JournalService,
    forge: str,
    repo: str,
    run: Correlation,
    origin: str | None,
) -> RepositoryJournal:
    return RepositoryJournal(
        journal, (run.workflow_id, run.run_id, forge, repo, None), origin
    )


def for_repository_run(
    journal: JournalService, forge: str, repo: str, run: Correlation
) -> RepositoryJournal:
    scope = (run.workflow_id, run.run_id, forge, repo, None)
    origins = _origins(journal, scope)
    if None in origins and len(origins) > 1:
        raise RepositoryAssociationUnresolvedError(
            "repository run contains unresolved journal entries"
        )
    if len(origins) > 1:
        raise AssociationConflictError(
            "repository run contains different origins"
        )
    return RepositoryJournal(journal, scope, next(iter(origins), None))
