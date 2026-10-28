"""What share of each repository's warnings is withheld, against a real
database.

Skipped unless DATABASE_URL names a Postgres server. The in-memory
double answers the same questions.
"""

import uuid

import pytest
import sqlalchemy as sa

from bugflow.review.domain.models.withholding import Withholding
from bugflow.review.infrastructure.sqlalchemy_withholding import (
    SqlAlchemyWithholding,
    repository_withholding,
)


def repo() -> str:
    return f"example/{uuid.uuid4()}"


def test_a_share_reads_back_for_its_repository(
    engine: sa.Engine, database_url: str
) -> None:
    withholding = SqlAlchemyWithholding(database_url)
    name = repo()
    withholding.declare(Withholding(forge="github", repo=name, share=0.25))

    assert withholding.share_for("github", name) == 0.25
    assert withholding.share_for("github", repo()) == 0.0


def test_declaring_again_replaces_the_share(
    engine: sa.Engine, database_url: str
) -> None:
    withholding = SqlAlchemyWithholding(database_url)
    name = repo()
    withholding.declare(Withholding(forge="github", repo=name, share=0.25))
    withholding.declare(Withholding(forge="github", repo=name, share=0.0))

    assert withholding.share_for("github", name) == 0.0
    assert Withholding(forge="github", repo=name, share=0.0) in (
        withholding.declarations()
    )


def test_a_share_set_out_of_range_by_hand_is_refused_where_it_is_read(
    engine: sa.Engine, database_url: str
) -> None:
    withholding = SqlAlchemyWithholding(database_url)
    name = repo()
    with engine.begin() as connection:
        connection.execute(
            repository_withholding.insert().values(
                forge="github", repo=name, share=1.5
            )
        )

    try:
        with pytest.raises(ValueError, match="between 0 and 1"):
            withholding.share_for("github", name)
        with pytest.raises(ValueError, match="between 0 and 1"):
            withholding.declarations()
    finally:
        with engine.begin() as connection:
            connection.execute(
                repository_withholding.delete().where(
                    repository_withholding.c.repo == name
                )
            )
