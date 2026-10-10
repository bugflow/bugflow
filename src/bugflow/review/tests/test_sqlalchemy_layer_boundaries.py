"""Where each repository's periods begin, against a real database.

Skipped unless DATABASE_URL names a Postgres server. The in-memory
double answers the same questions, and the two are kept alike on
purpose: an adapter shipped with only its double under test can fail on
every page that reads it.
"""

import uuid

import sqlalchemy as sa

from bugflow.review.domain.models.cadence_boundary import CadenceBoundary
from bugflow.review.domain.models.layer_boundary import LayerBoundary
from bugflow.review.infrastructure.sqlalchemy_cadence_boundaries import (
    SqlAlchemyCadenceBoundaries,
)
from bugflow.review.infrastructure.sqlalchemy_layer_boundaries import (
    SqlAlchemyLayerBoundaries,
)


def repo() -> str:
    return f"example/{uuid.uuid4()}"


def declare(
    boundaries: SqlAlchemyLayerBoundaries, name: str, layer: str, at: str
) -> None:
    boundaries.declare(
        LayerBoundary(forge="github", repo=name, layer=layer, boundary=at)
    )


def test_a_boundary_reads_back_for_its_repository_and_layer(
    engine: sa.Engine, database_url: str
) -> None:
    boundaries = SqlAlchemyLayerBoundaries(database_url)
    name = repo()
    declare(boundaries, name, "weekly", "SUN 23:30")

    assert boundaries.boundary("github", name, "weekly") == "SUN 23:30"
    assert boundaries.boundary("github", name, "pull-request") is None


def test_two_repositories_on_one_layer_begin_where_each_says(
    engine: sa.Engine, database_url: str
) -> None:
    """One cadence, two phases, which one calendar for the whole server
    cannot say."""
    boundaries = SqlAlchemyLayerBoundaries(database_url)
    first, second = repo(), repo()
    declare(boundaries, first, "fortnightly", "2026-09-01 09:00")
    declare(boundaries, second, "fortnightly", "2026-09-11 17:00")

    assert (
        boundaries.boundary("github", first, "fortnightly")
        == "2026-09-01 09:00"
    )
    assert (
        boundaries.boundary("github", second, "fortnightly")
        == "2026-09-11 17:00"
    )


def test_declaring_again_moves_that_boundary_and_no_other(
    engine: sa.Engine, database_url: str
) -> None:
    boundaries = SqlAlchemyLayerBoundaries(database_url)
    name = repo()
    declare(boundaries, name, "weekly", "SUN 23:30")
    declare(boundaries, name, "pull-request", "60s")
    declare(boundaries, name, "weekly", "MON 06:00")

    assert boundaries.boundary("github", name, "weekly") == "MON 06:00"
    assert boundaries.boundary("github", name, "pull-request") == "60s"


def test_withdrawing_leaves_nothing_to_fall_back_to(
    engine: sa.Engine, database_url: str
) -> None:
    boundaries = SqlAlchemyLayerBoundaries(database_url)
    name = repo()
    declare(boundaries, name, "weekly", "SUN 23:30")
    boundaries.withdraw("github", name, "weekly")

    assert boundaries.boundary("github", name, "weekly") is None


def test_every_boundary_is_listed_for_a_page_to_show(
    engine: sa.Engine, database_url: str
) -> None:
    boundaries = SqlAlchemyLayerBoundaries(database_url)
    name = repo()
    declare(boundaries, name, "weekly", "SUN 23:30")
    declare(boundaries, name, "pull-request", "60s")

    mine = [one for one in boundaries.declarations() if one.repo == name]
    assert [(one.layer, one.boundary) for one in mine] == [
        ("pull-request", "60s"),
        ("weekly", "SUN 23:30"),
    ]


def test_the_server_keeps_one_boundary_per_cadence(
    engine: sa.Engine, database_url: str
) -> None:
    """The row an allowance scoped wider than any repository reads."""
    cadences = SqlAlchemyCadenceBoundaries(database_url)
    cadences.declare(CadenceBoundary(cadence="weekly", boundary="SUN 23:30"))

    assert cadences.boundary("weekly") == "SUN 23:30"

    cadences.declare(CadenceBoundary(cadence="weekly", boundary="MON 00:00"))
    assert cadences.boundary("weekly") == "MON 00:00"
    assert CadenceBoundary(cadence="weekly", boundary="MON 00:00") in (
        cadences.declarations()
    )

    cadences.withdraw("weekly")
    assert cadences.boundary("weekly") is None
