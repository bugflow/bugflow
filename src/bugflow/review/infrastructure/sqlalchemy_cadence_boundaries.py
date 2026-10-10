"""Where this server's periods begin, in Postgres.

One row per cadence. The table definition mirrors the script that
creates it.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from bugflow.review.domain.models.cadence_boundary import CadenceBoundary
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()

cadence_boundaries = sa.Table(
    "cadence_boundaries",
    metadata,
    sa.Column("cadence", sa.Text, primary_key=True),
    sa.Column("boundary", sa.Text, nullable=False),
    sa.Column(
        "declared_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)


class SqlAlchemyCadenceBoundaries:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def boundary(self, cadence: str) -> str | None:
        query = sa.select(cadence_boundaries.c.boundary).where(
            cadence_boundaries.c.cadence == cadence
        )
        with self._engine.connect() as connection:
            found = connection.execute(query).scalar()
        return str(found) if found is not None else None

    def declarations(self) -> list[CadenceBoundary]:
        query = sa.select(cadence_boundaries).order_by(
            cadence_boundaries.c.cadence
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [
            CadenceBoundary(cadence=row["cadence"], boundary=row["boundary"])
            for row in rows
        ]

    def declare(self, boundary: CadenceBoundary) -> None:
        statement = (
            insert(cadence_boundaries)
            .values(cadence=boundary.cadence, boundary=boundary.boundary)
            .on_conflict_do_update(
                index_elements=["cadence"],
                set_={
                    "boundary": boundary.boundary,
                    "declared_at": sa.func.now(),
                },
            )
        )
        with self._engine.begin() as connection:
            connection.execute(statement)

    def withdraw(self, cadence: str) -> None:
        statement = sa.delete(cadence_boundaries).where(
            cadence_boundaries.c.cadence == cadence
        )
        with self._engine.begin() as connection:
            connection.execute(statement)
