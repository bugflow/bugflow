"""Where each repository's periods begin, in Postgres.

One row per repository per layer, keyed on all three, so declaring a
boundary on one layer cannot disturb another. The table definition
mirrors the script that creates it.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from bugflow.review.domain.models.layer_boundary import LayerBoundary
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()

layer_boundaries = sa.Table(
    "repository_layer_boundaries",
    metadata,
    sa.Column("forge", sa.Text, primary_key=True),
    sa.Column("repo", sa.Text, primary_key=True),
    sa.Column("layer", sa.Text, primary_key=True),
    sa.Column("boundary", sa.Text, nullable=False),
    sa.Column(
        "declared_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)


class SqlAlchemyLayerBoundaries:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def boundary(self, forge: str, repo: str, layer: str) -> str | None:
        query = sa.select(layer_boundaries.c.boundary).where(
            layer_boundaries.c.forge == forge,
            layer_boundaries.c.repo == repo,
            layer_boundaries.c.layer == layer,
        )
        with self._engine.connect() as connection:
            found = connection.execute(query).scalar()
        return str(found) if found is not None else None

    def declarations(self) -> list[LayerBoundary]:
        query = sa.select(layer_boundaries).order_by(
            layer_boundaries.c.forge,
            layer_boundaries.c.repo,
            layer_boundaries.c.layer,
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [
            LayerBoundary(
                forge=row["forge"],
                repo=row["repo"],
                layer=row["layer"],
                boundary=row["boundary"],
            )
            for row in rows
        ]

    def declare(self, boundary: LayerBoundary) -> None:
        statement = (
            insert(layer_boundaries)
            .values(
                forge=boundary.forge,
                repo=boundary.repo,
                layer=boundary.layer,
                boundary=boundary.boundary,
            )
            .on_conflict_do_update(
                index_elements=["forge", "repo", "layer"],
                set_={
                    "boundary": boundary.boundary,
                    "declared_at": sa.func.now(),
                },
            )
        )
        with self._engine.begin() as connection:
            connection.execute(statement)

    def withdraw(self, forge: str, repo: str, layer: str) -> None:
        statement = sa.delete(layer_boundaries).where(
            layer_boundaries.c.forge == forge,
            layer_boundaries.c.repo == repo,
            layer_boundaries.c.layer == layer,
        )
        with self._engine.begin() as connection:
            connection.execute(statement)
