"""What share of each repository's warnings is withheld, in Postgres.

One row per repository; a repository with no row withholds nothing. The
table definition mirrors the script that creates it.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from bugflow.review.domain.models.withholding import Withholding
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()

repository_withholding = sa.Table(
    "repository_withholding",
    metadata,
    sa.Column("forge", sa.Text, primary_key=True),
    sa.Column("repo", sa.Text, primary_key=True),
    sa.Column("share", sa.Float, nullable=False),
    sa.Column(
        "declared_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)


class SqlAlchemyWithholding:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def share_for(self, forge: str, repo: str) -> float:
        query = sa.select(repository_withholding.c.share).where(
            repository_withholding.c.forge == forge,
            repository_withholding.c.repo == repo,
        )
        with self._engine.connect() as connection:
            found = connection.execute(query).scalar()
        return float(found) if found is not None else 0.0

    def declarations(self) -> list[Withholding]:
        query = sa.select(repository_withholding).order_by(
            repository_withholding.c.forge, repository_withholding.c.repo
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [
            Withholding(
                forge=row["forge"], repo=row["repo"], share=float(row["share"])
            )
            for row in rows
        ]

    def declare(self, withholding: Withholding) -> None:
        statement = (
            insert(repository_withholding)
            .values(
                forge=withholding.forge,
                repo=withholding.repo,
                share=withholding.share,
            )
            .on_conflict_do_update(
                index_elements=["forge", "repo"],
                set_={
                    "share": withholding.share,
                    "declared_at": sa.func.now(),
                },
            )
        )
        with self._engine.begin() as connection:
            connection.execute(statement)
