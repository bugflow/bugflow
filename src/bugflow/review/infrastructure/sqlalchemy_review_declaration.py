"""What a repository is reviewed for, in Postgres.

One row per repository per name, so removing one name is a delete
rather than a rewrite of a list. The table definitions mirror the
script that creates them.

Two tables for two interfaces, which is this adapter's choice rather
than the domain's: what is one concept and what is two is the domain's,
and where an adapter keeps what it holds is its own.
"""

import sqlalchemy as sa

from bugflow.review.domain.models.review_declaration import (
    DispatchedProcesses,
    JudgedPolicies,
)
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()


def _table(name: str, column: str) -> sa.Table:
    return sa.Table(
        name,
        metadata,
        sa.Column("forge", sa.Text, primary_key=True),
        sa.Column("repo", sa.Text, primary_key=True),
        sa.Column(column, sa.Text, primary_key=True),
        sa.Column(
            "declared_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


judged_policies = _table("repository_judged_policies", "policy_id")
dispatched_processes = _table("repository_dispatched_processes", "process")


class _Declared:
    """The half both adapters share: a set of names per repository.

    Not an interface and not a base class anybody outside this module
    uses.
    """

    def __init__(self, database_url: str, table: sa.Table, column: str):
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )
        self._table = table
        self._column = table.c[column]

    def _named(self, forge: str, repo: str) -> frozenset[str]:
        query = sa.select(self._column).where(
            self._table.c.forge == forge, self._table.c.repo == repo
        )
        with self._engine.connect() as connection:
            return frozenset(row[0] for row in connection.execute(query))

    def _all(self) -> dict[tuple[str, str], tuple[str, ...]]:
        query = sa.select(
            self._table.c.forge, self._table.c.repo, self._column
        ).order_by(self._table.c.forge, self._table.c.repo, self._column)
        held: dict[tuple[str, str], tuple[str, ...]] = {}
        with self._engine.connect() as connection:
            for forge, repo, name in connection.execute(query):
                held[(forge, repo)] = (*held.get((forge, repo), ()), name)
        return held

    def _replace(self, forge: str, repo: str, names: tuple[str, ...]) -> None:
        """Replace the whole set at once, in one transaction.

        A delete and an insert rather than a merge, because the
        declaration is a set: a name absent from what the caller sent is
        a name that is no longer declared, and a merge would leave it on.
        """
        with self._engine.begin() as connection:
            connection.execute(
                sa.delete(self._table).where(
                    self._table.c.forge == forge,
                    self._table.c.repo == repo,
                )
            )
            if names:
                connection.execute(
                    sa.insert(self._table),
                    [
                        {
                            "forge": forge,
                            "repo": repo,
                            self._column.name: name,
                        }
                        for name in dict.fromkeys(names)
                    ],
                )


class SqlAlchemyJudgedPolicies(_Declared):
    def __init__(self, database_url: str) -> None:
        super().__init__(database_url, judged_policies, "policy_id")

    def judged(self, forge: str, repo: str) -> frozenset[str]:
        return self._named(forge, repo)

    def declarations(self) -> list[JudgedPolicies]:
        return [
            JudgedPolicies(forge=forge, repo=repo, policies=names)
            for (forge, repo), names in sorted(self._all().items())
        ]

    def declare(self, declaration: JudgedPolicies) -> None:
        self._replace(
            declaration.forge, declaration.repo, declaration.policies
        )


class SqlAlchemyDispatchedProcesses(_Declared):
    def __init__(self, database_url: str) -> None:
        super().__init__(database_url, dispatched_processes, "process")

    def dispatched(self, forge: str, repo: str) -> frozenset[str]:
        return self._named(forge, repo)

    def declarations(self) -> list[DispatchedProcesses]:
        return [
            DispatchedProcesses(forge=forge, repo=repo, processes=names)
            for (forge, repo), names in sorted(self._all().items())
        ]

    def declare(self, declaration: DispatchedProcesses) -> None:
        self._replace(
            declaration.forge, declaration.repo, declaration.processes
        )
