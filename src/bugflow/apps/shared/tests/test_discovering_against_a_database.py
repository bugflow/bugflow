"""Tests of discovery composed over Postgres: a renamed repository keeps
its row and its settings, and every gnome on an archived one is switched
off. Skipped unless DATABASE_URL names a Postgres server."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from bugflow.apps.shared.discovering import DISCOVERY, Discovering, discover
from bugflow.forge.domain.models.forge_repository import ListedRepository
from bugflow.forge.infrastructure.sqlalchemy_known_repositories import (
    SqlAlchemyKnownRepositories,
)
from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
)
from bugflow.shared.infrastructure.migrations import upgrade
from bugflow.shared.tests.postgres import scratch_database


@pytest.fixture
def database_url() -> Iterator[str]:
    for url in scratch_database():
        upgrade(url)
        yield url


class Listing:
    def __init__(self, *repositories: ListedRepository) -> None:
        self.repositories = list(repositories)

    def repositories_of(self, owner: str) -> list[ListedRepository]:
        return self.repositories


def listed(name: str, archived: bool = False) -> ListedRepository:
    return ListedRepository(
        forge="github", name=name, forge_key="77", archived=archived
    )


def advise(database_url: str, repo: str) -> None:
    SqlAlchemyGnomeSettings(database_url).save(
        GnomeSetting(
            forge="github",
            repo=repo,
            gnome="pr-gnome",
            behaviour="advise",
            set_by="a test",
            set_at=datetime.now(UTC),
        )
    )


def test_a_renamed_repository_keeps_its_settings(database_url: str) -> None:
    listing = Listing(listed("acme/before"))
    run = Discovering(
        database_url=database_url, owners=("acme",), listing=listing
    )
    discover(run)
    advise(database_url, "acme/before")

    listing.repositories = [listed("acme/after")]
    found = discover(run)

    assert [(one.change, one.was_name) for one in found.changes] == [
        ("renamed", "acme/before")
    ]
    (kept,) = SqlAlchemyGnomeSettings(database_url).settings()
    assert (kept.repo, kept.behaviour) == ("acme/after", "advise")
    assert [
        one.name
        for one in SqlAlchemyKnownRepositories(database_url).known(
            "github", "acme"
        )
    ] == ["acme/after"]


def test_every_gnome_on_an_archived_repository_is_switched_off(
    database_url: str,
) -> None:
    listing = Listing(listed("acme/shelved"))
    run = Discovering(
        database_url=database_url, owners=("acme",), listing=listing
    )
    discover(run)
    advise(database_url, "acme/shelved")

    listing.repositories = [listed("acme/shelved", archived=True)]
    discover(run)

    (kept,) = SqlAlchemyGnomeSettings(database_url).settings()
    assert (kept.behaviour, kept.set_by) == ("off", DISCOVERY)


def test_a_rename_onto_a_held_name_is_recorded_once_and_both_rows_stay(
    database_url: str,
) -> None:
    listing = Listing(listed("acme/before"))
    run = Discovering(
        database_url=database_url, owners=("acme",), listing=listing
    )
    discover(run)
    advise(database_url, "acme/after")

    listing.repositories = [listed("acme/after", archived=True)]
    first = discover(run)
    again = discover(run)

    assert [one.change for one in first.changes] == ["renamed", "archived"]
    assert again.changes == ()
    assert sorted(
        (one.name, one.forge_key)
        for one in SqlAlchemyKnownRepositories(database_url).known(
            "github", "acme"
        )
    ) == [("acme/after", "77"), ("acme/before", None)]
    (kept,) = SqlAlchemyGnomeSettings(database_url).settings()
    assert (kept.repo, kept.behaviour) == ("acme/after", "off")


def test_whether_a_repository_is_private_is_kept_as_listed(
    database_url: str,
) -> None:
    listing = Listing(
        ListedRepository(
            forge="github", name="acme/hidden", forge_key="88", private=True
        )
    )
    run = Discovering(
        database_url=database_url, owners=("acme",), listing=listing
    )
    discover(run)
    listing.repositories = [
        ListedRepository(
            forge="github", name="acme/hidden", forge_key="88", private=False
        )
    ]
    discover(run)

    (held,) = SqlAlchemyKnownRepositories(database_url).everything()
    assert held.private is False
