"""Spend bindings in Postgres.

A row binds a ceiling to a scope, and an empty column means "any". The
table definition mirrors the script that creates it.

Every query is ordered by how much of the scope is named, so the
narrowest row comes back first. All of them apply: a ceiling for one
repository's weekly run of one reviewer and one for the repository are
two limits, and a run must satisfy both.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()
spend_bindings = sa.Table(
    "spend_bindings",
    metadata,
    # Empty rather than null for "any", so the primary key holds: null
    # is not equal to null, and two unscoped rows would both be allowed
    # in.
    sa.Column("forge", sa.Text, primary_key=True, server_default=""),
    sa.Column("repo", sa.Text, primary_key=True, server_default=""),
    sa.Column("layer", sa.Text, primary_key=True, server_default=""),
    sa.Column("agent_id", sa.Text, primary_key=True, server_default=""),
    # A limit, and a null limit is no limit.
    sa.Column("usd", sa.Float),
    sa.Column("turns", sa.Float),
    # What shares the allowance, and part of what identifies the row:
    # one scope holds a limit per event and a limit per period, which
    # are two allowances rather than one overwriting the other.
    sa.Column(
        "per",
        sa.Text,
        primary_key=True,
        nullable=False,
        server_default="event",
    ),
    sa.Column(
        "declared_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)

#: How specific a row is: the number of scope columns it names. The
#: most specific match is the ceiling that applies.
_NAMED = (
    sa.case((spend_bindings.c.forge != "", 1), else_=0)
    + sa.case((spend_bindings.c.repo != "", 1), else_=0)
    + sa.case((spend_bindings.c.layer != "", 1), else_=0)
    + sa.case((spend_bindings.c.agent_id != "", 1), else_=0)
)


def _binding(
    row: sa.Row[tuple[str, str, str, str, float, float]],
) -> SpendBinding:
    return SpendBinding(
        scope=SpendScope(
            forge=row.forge,
            repo=row.repo,
            layer=row.layer,
            agent_id=row.agent_id,
        ),
        budget=Budget(usd=row.usd, turns=row.turns),
        per=row.per,
    )


class SqlAlchemySpendBindings:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def binding_for(
        self, forge: str, repo: str, layer: str, agent_id: str
    ) -> list[SpendBinding]:
        """Return every row whose scope covers this run, most specific
        first.

        One query rather than one per scope: a dispatch reads this
        beside a call to a forge and a model, and four round trips
        where one will do is a cost nobody asked for.
        """
        query = (
            sa.select(spend_bindings)
            .where(
                spend_bindings.c.forge.in_(("", forge)),
                spend_bindings.c.repo.in_(("", repo)),
                spend_bindings.c.layer.in_(("", layer)),
                spend_bindings.c.agent_id.in_(("", agent_id)),
            )
            .order_by(_NAMED.desc())
        )
        with self._engine.connect() as connection:
            return [_binding(row) for row in connection.execute(query)]

    def bindings(self) -> list[SpendBinding]:
        query = sa.select(spend_bindings).order_by(
            _NAMED.desc(),
            spend_bindings.c.forge,
            spend_bindings.c.repo,
            spend_bindings.c.layer,
            spend_bindings.c.agent_id,
        )
        with self._engine.connect() as connection:
            return [_binding(row) for row in connection.execute(query)]

    def revoke(self, scope: SpendScope, per: str) -> None:
        statement = sa.delete(spend_bindings).where(
            spend_bindings.c.forge == scope.forge,
            spend_bindings.c.repo == scope.repo,
            spend_bindings.c.layer == scope.layer,
            spend_bindings.c.agent_id == scope.agent_id,
            spend_bindings.c.per == per,
        )
        with self._engine.begin() as connection:
            connection.execute(statement)

    def declare(self, binding: SpendBinding) -> None:
        scope = binding.scope
        statement = insert(spend_bindings).values(
            forge=scope.forge,
            repo=scope.repo,
            layer=scope.layer,
            agent_id=scope.agent_id,
            usd=binding.budget.usd,
            turns=binding.budget.turns,
            per=binding.per,
        )
        statement = statement.on_conflict_do_update(
            index_elements=["forge", "repo", "layer", "agent_id", "per"],
            set_={
                "usd": statement.excluded.usd,
                "turns": statement.excluded.turns,
                "declared_at": sa.func.now(),
            },
        )
        with self._engine.begin() as connection:
            connection.execute(statement)
