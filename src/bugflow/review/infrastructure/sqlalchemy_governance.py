"""Which agents govern a repository's review label, in Postgres.

A row says an agent governs this repository or does not; a repository
nobody has decided about is governed by the deployment's default, so
switching an agent on for one team is an insert and not a release. The
table definition mirrors the script that creates it.
"""

from collections.abc import Iterable

import sqlalchemy as sa

from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()
governance = sa.Table(
    "review_governance",
    metadata,
    sa.Column("forge", sa.Text, primary_key=True),
    sa.Column("repo", sa.Text, primary_key=True),
    sa.Column("agent_id", sa.Text, primary_key=True),
    sa.Column("governs", sa.Boolean, nullable=False),
    sa.Column(
        "decided_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)


class SqlAlchemyGovernance:
    """The deployment's default, overridden per repository by what is
    stored.

    An override is per agent rather than a whole set, so switching one
    agent on for a team leaves the rest of that team's governance alone
    and following the default.
    """

    def __init__(self, database_url: str, default: Iterable[str]) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )
        self._default = frozenset(default)

    def governing_agents(self, forge: str, repo: str) -> frozenset[str]:
        statement = sa.select(
            governance.c.agent_id, governance.c.governs
        ).where(governance.c.forge == forge, governance.c.repo == repo)
        with self._engine.connect() as connection:
            decided = {
                row.agent_id: row.governs
                for row in connection.execute(statement)
            }
        governing = set(self._default)
        for agent_id, governs in decided.items():
            if governs:
                governing.add(agent_id)
            else:
                governing.discard(agent_id)
        return frozenset(governing)
