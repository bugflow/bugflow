"""Tests of discovering what changed among an owner's repositories at
their forge (ADR 008)."""

from datetime import UTC, datetime

from bugflow.forge.domain.errors import ForgeUnavailableError
from bugflow.forge.domain.models.forge_repository import (
    KnownRepository,
    ListedRepository,
    RepositoryChange,
)
from bugflow.forge.dtos.discover_repositories import (
    DiscoverRepositoriesRequest,
)
from bugflow.forge.infrastructure.sqlalchemy_known_repositories import (
    InMemoryKnownRepositories,
)
from bugflow.forge.usecases.discover_repositories import (
    DiscoverRepositoriesUseCase,
)
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

RUN = Correlation(workflow_id="repositories/discover", run_id="r-1")


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 10, 27, tzinfo=UTC)


class Listing:
    def __init__(self, **by_owner: list[ListedRepository]) -> None:
        self._by_owner = by_owner

    def repositories_of(self, owner: str) -> list[ListedRepository]:
        if owner not in self._by_owner:
            raise ForgeUnavailableError("could not reach GitHub")
        return self._by_owner[owner]


def listed(name: str, key: str, archived: bool = False) -> ListedRepository:
    return ListedRepository(
        forge="github", name=name, forge_key=key, archived=archived
    )


def discovered(
    listing: Listing, *known: KnownRepository
) -> tuple[list[RepositoryChange], InMemoryJournal, InMemoryKnownRepositories]:
    journal, held = InMemoryJournal(), InMemoryKnownRepositories(*known)
    found = DiscoverRepositoriesUseCase(
        listing, held, journal, FixedClock()
    ).execute(
        DiscoverRepositoriesRequest(owners=("gs-gs", "gone"), correlation=RUN)
    )
    assert found.failures == ("gone: could not reach GitHub",)
    return list(found.changes), journal, held


def test_a_repository_listed_for_the_first_time_is_discovered() -> None:
    changes, journal, held = discovered(
        Listing(**{"gs-gs": [listed("gs-gs/new", "1")]})
    )
    assert changes == [
        RepositoryChange(forge="github", name="gs-gs/new", change="discovered")
    ]
    (entry,) = journal.entries
    assert entry.event_type == "repository.found"
    assert entry.payload["forge_key"] == "1"
    assert held.known("github", "gs-gs")[0].forge_key == "1"


def test_a_repository_known_from_the_journal_takes_its_key_quietly() -> None:
    changes, journal, held = discovered(
        Listing(**{"gs-gs": [listed("gs-gs/old", "2")]}),
        KnownRepository(forge="github", name="gs-gs/old"),
    )
    assert changes == [] and journal.entries == []
    assert held.known("github", "gs-gs")[0].forge_key == "2"


def test_a_repository_whose_key_has_a_new_name_is_renamed() -> None:
    changes, _, held = discovered(
        Listing(**{"gs-gs": [listed("gs-gs/after", "3")]}),
        KnownRepository(forge="github", name="gs-gs/before", forge_key="3"),
    )
    assert changes == [
        RepositoryChange(
            forge="github",
            name="gs-gs/after",
            change="renamed",
            was_name="gs-gs/before",
        )
    ]
    assert [one.name for one in held.known("github", "gs-gs")] == [
        "gs-gs/after"
    ]


def test_archiving_is_found_both_ways() -> None:
    changes, _, _ = discovered(
        Listing(
            **{
                "gs-gs": [
                    listed("gs-gs/shelved", "4", archived=True),
                    listed("gs-gs/revived", "5"),
                ]
            }
        ),
        KnownRepository(forge="github", name="gs-gs/shelved", forge_key="4"),
        KnownRepository(
            forge="github", name="gs-gs/revived", forge_key="5", archived=True
        ),
    )
    assert {(one.name, one.change) for one in changes} == {
        ("gs-gs/shelved", "archived"),
        ("gs-gs/revived", "unarchived"),
    }


def test_nothing_changed_records_nothing() -> None:
    changes, journal, _ = discovered(
        Listing(**{"gs-gs": [listed("gs-gs/same", "6")]}),
        KnownRepository(forge="github", name="gs-gs/same", forge_key="6"),
    )
    assert changes == [] and journal.entries == []


def test_a_repository_archived_when_first_listed_is_archived() -> None:
    changes, _, _ = discovered(
        Listing(**{"gs-gs": [listed("gs-gs/old", "7", archived=True)]}),
        KnownRepository(forge="github", name="gs-gs/old"),
    )
    assert [(one.name, one.change) for one in changes] == [
        ("gs-gs/old", "archived")
    ]


def test_a_repository_renamed_and_archived_is_both() -> None:
    changes, _, _ = discovered(
        Listing(**{"gs-gs": [listed("gs-gs/after", "8", archived=True)]}),
        KnownRepository(forge="github", name="gs-gs/before", forge_key="8"),
    )
    assert [one.change for one in changes] == ["renamed", "archived"]


def test_a_repository_moved_to_another_owner_is_renamed() -> None:
    changes, _, held = discovered(
        Listing(**{"gs-gs": [listed("gs-gs/moved", "9")]}),
        KnownRepository(forge="github", name="gs-dawr/moved", forge_key="9"),
    )
    assert [(one.change, one.was_name) for one in changes] == [
        ("renamed", "gs-dawr/moved")
    ]
    assert [one.name for one in held.held] == ["gs-gs/moved"]


def test_a_rename_onto_a_held_name_is_recorded_once() -> None:
    listing = Listing(**{"gs-gs": [listed("gs-gs/after", "10")]})
    held = InMemoryKnownRepositories(
        KnownRepository(forge="github", name="gs-gs/before", forge_key="10"),
        KnownRepository(forge="github", name="gs-gs/after"),
    )
    run = DiscoverRepositoriesUseCase(
        listing, held, InMemoryJournal(), FixedClock()
    )
    request = DiscoverRepositoriesRequest(owners=("gs-gs",), correlation=RUN)

    first = run.execute(request).changes
    again = run.execute(request).changes

    assert [one.change for one in first] == ["renamed"]
    assert again == ()
    assert sorted((one.name, one.forge_key) for one in held.held) == [
        ("gs-gs/after", "10"),
        ("gs-gs/before", None),
    ]
