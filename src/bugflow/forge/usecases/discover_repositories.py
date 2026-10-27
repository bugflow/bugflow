"""Use case: find what has changed among an owner's repositories at
their forge, and keep it (ADR 008).

A repository listed for the first time is discovered, and every gnome
is ``off`` on it until someone sets one. A repository whose forge key is
known under another name is renamed, and keeps its row and so its
settings. A repository's archiving is recorded both ways. Each change is
written to the journal as ``repository.found`` before it is kept, so a
row never changes without its record.

A repository the server knew from its journal before it was listed takes
its forge key when it is first listed, and that is not a change, though
its being archived then is.

A repository is matched by its forge key across all of its forge's
rows, so one moved to another owner is renamed. A rename onto a name
another row already holds is recorded once: the key moves to that row,
and both rows are left, each with its own settings.
"""

from bugflow.forge.domain import facts
from bugflow.forge.domain.errors import ForgeError
from bugflow.forge.domain.models.forge_repository import (
    Change,
    KnownRepository,
    ListedRepository,
    RepositoryChange,
)
from bugflow.forge.domain.repositories.known_repositories import (
    KnownRepositoriesRepository,
)
from bugflow.forge.domain.services.repository_listing import (
    RepositoryListingService,
)
from bugflow.forge.dtos.discover_repositories import (
    DiscoverRepositoriesRequest,
    DiscoverRepositoriesResponse,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService


def _changes(
    listed: ListedRepository, known: list[KnownRepository]
) -> list[tuple[Change, str | None]]:
    """What changed about the listed repository, each with the name it
    had before a rename."""
    by_key = next(
        (one for one in known if one.forge_key == listed.forge_key), None
    )
    by_name = next((one for one in known if one.name == listed.name), None)
    if by_key is None and by_name is None:
        return [("discovered", None)]
    found: list[tuple[Change, str | None]] = []
    if by_key is not None and by_key.name != listed.name:
        found.append(("renamed", by_key.name))
    # The row that holds the repository once it is kept.
    held = by_name or by_key
    assert held is not None
    if held.archived != listed.archived:
        found.append(("archived" if listed.archived else "unarchived", None))
    return found


class DiscoverRepositoriesUseCase:
    def __init__(
        self,
        listing: RepositoryListingService,
        known: KnownRepositoriesRepository,
        journal: RecordingService,
        clock: ClockService,
    ) -> None:
        self._listing = listing
        self._known = known
        self._journal = journal
        self._clock = clock

    def execute(
        self, request: DiscoverRepositoriesRequest
    ) -> DiscoverRepositoriesResponse:
        changes: list[RepositoryChange] = []
        failures: list[str] = []
        for owner in request.owners:
            try:
                listed = self._listing.repositories_of(owner)
            except ForgeError as exc:
                failures.append(f"{owner}: {exc}")
                continue
            known = self._known.known(
                request.forge, owner, {one.forge_key for one in listed}
            )
            for one in sorted(listed, key=lambda r: r.name):
                for change, was in _changes(one, known):
                    self._journal.append(
                        [self._entry(request, one, change, was)]
                    )
                    changes.append(
                        RepositoryChange(
                            forge=one.forge,
                            name=one.name,
                            change=change,
                            was_name=was,
                        )
                    )
                self._known.keep(one)
        return DiscoverRepositoriesResponse(
            changes=tuple(changes), failures=tuple(failures)
        )

    def _entry(
        self,
        request: DiscoverRepositoriesRequest,
        listed: ListedRepository,
        change: Change,
        was: str | None,
    ) -> JournalEntry:
        when = self._clock.now()
        return JournalEntry(
            event_id=facts.repository_found_id(
                listed.forge,
                listed.forge_key,
                change,
                listed.name,
                when.isoformat(),
            ),
            occurred_at=when,
            event_type=facts.REPOSITORY_FOUND,
            forge=listed.forge,
            # A rename is recorded under the name the server holds the
            # repository by, since the journal finds the repository's row
            # by its name, and the row is renamed after the record.
            repo=was or listed.name,
            pr_number=None,
            commit_sha=None,
            corpus_version=None,
            workflow_id=request.correlation.workflow_id,
            run_id=request.correlation.run_id,
            payload={
                "change": change,
                "forge_key": listed.forge_key,
                "archived": listed.archived,
                "was_name": was,
            },
        )
