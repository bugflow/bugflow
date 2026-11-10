"""The deployments this server was sent, in Postgres.

Three tables, which is this adapter's choice: a deployment by the names
it was sent under and the tenant it was sent for, its files one row
each, and one row for each time a deployment was put in force. The last
of those is only added to, so what was in force on a day stays
answerable. Each tenant's rows are read apart (ADR 011). The table
definitions mirror the script that creates them.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

import sqlalchemy as sa

from bugflow.method.domain.errors import PolicyDeploymentConflictError
from bugflow.method.domain.models.policy_deployment import (
    DEFAULT_TENANT,
    DeployedFile,
    PolicyDeployment,
    PutInForce,
)
from bugflow.method.domain.repositories.policy_deployment import Facts
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.infrastructure.database import (
    shared_engine,
)

metadata = sa.MetaData()


def _tenant(primary_key: bool) -> sa.Column[str]:
    # The default is the tenant of a server that names none, so a row
    # written by a program older than the column is that tenant's.
    return sa.Column(
        "tenant",
        sa.Text,
        primary_key=primary_key,
        nullable=False,
        server_default=DEFAULT_TENANT,
    )


deployments = sa.Table(
    "policy_deployment",
    metadata,
    _tenant(primary_key=True),
    sa.Column("repository", sa.Text, primary_key=True),
    sa.Column("commit", sa.Text, primary_key=True),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column(
        "received_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)

files = sa.Table(
    "policy_deployment_file",
    metadata,
    _tenant(primary_key=True),
    sa.Column("repository", sa.Text, primary_key=True),
    sa.Column("commit", sa.Text, primary_key=True),
    sa.Column("path", sa.Text, primary_key=True),
    sa.Column("text", sa.Text, nullable=False),
    sa.ForeignKeyConstraint(
        ["tenant", "repository", "commit"],
        [
            "policy_deployment.tenant",
            "policy_deployment.repository",
            "policy_deployment.commit",
        ],
    ),
)

in_force = sa.Table(
    "policy_deployment_in_force",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    _tenant(primary_key=False),
    sa.Column("repository", sa.Text, nullable=False),
    sa.Column("commit", sa.Text, nullable=False),
    sa.Column(
        "put_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.ForeignKeyConstraint(
        ["tenant", "repository", "commit"],
        [
            "policy_deployment.tenant",
            "policy_deployment.repository",
            "policy_deployment.commit",
        ],
    ),
)


class JournalOnAConnection(Protocol):
    """A journal in the same database that appends in the caller's
    transaction."""

    def append_on(
        self, connection: sa.Connection, entries: Sequence[JournalEntry]
    ) -> None: ...


class SqlAlchemyPolicyDeployments:
    """Implements ``PolicyDeploymentRepository`` over Postgres.

    ``journal`` is where the facts of a deployment are recorded. A store
    given none refuses a deployment that has facts to record.
    """

    def __init__(
        self, database_url: str, journal: JournalOnAConnection | None = None
    ) -> None:
        self._engine = shared_engine(database_url)
        self._journal = journal

    def deploy(
        self, deployment: PolicyDeployment, facts: Facts = lambda _: ()
    ) -> bool:
        """Store, put in force and record in one transaction, so a
        deployment is never in force with only some of its files, or
        without the facts that record it."""
        tenant = deployment.tenant
        repository, commit = deployment.repository, deployment.commit
        with self._engine.begin() as connection:
            earlier = connection.execute(
                sa.select(deployments.c.content_hash).where(
                    deployments.c.tenant == tenant,
                    deployments.c.repository == repository,
                    deployments.c.commit == commit,
                )
            ).scalar_one_or_none()
            if earlier is None:
                connection.execute(
                    sa.insert(deployments).values(
                        tenant=tenant,
                        repository=repository,
                        commit=commit,
                        content_hash=deployment.content_hash,
                    )
                )
                if deployment.files:
                    connection.execute(
                        sa.insert(files),
                        [
                            {
                                "tenant": tenant,
                                "repository": repository,
                                "commit": commit,
                                "path": one.path,
                                "text": one.text,
                            }
                            for one in deployment.files
                        ],
                    )
            elif earlier != deployment.content_hash:
                raise PolicyDeploymentConflictError(repository, commit)
            latest = connection.execute(
                self._puts(tenant).limit(1)
            ).one_or_none()
            replaced = None if latest is None else self._put(latest)
            if replaced and (replaced.repository, replaced.commit) == (
                repository,
                commit,
            ):
                return False
            connection.execute(
                sa.insert(in_force).values(
                    tenant=tenant, repository=repository, commit=commit
                )
            )
            recorded = facts(replaced)
            if recorded:
                if self._journal is None:
                    raise ValueError(
                        "this store has no journal to record the "
                        "deployment's facts in"
                    )
                self._journal.append_on(connection, recorded)
            return True

    def in_force(
        self, tenant: str = DEFAULT_TENANT
    ) -> PolicyDeployment | None:
        with self._engine.connect() as connection:
            latest = connection.execute(
                self._puts(tenant).limit(1)
            ).one_or_none()
            if latest is None:
                return None
            return self._read(connection, tenant, latest[0], latest[1])

    def last_put_in_force(
        self, tenant: str = DEFAULT_TENANT
    ) -> PutInForce | None:
        with self._engine.connect() as connection:
            row = connection.execute(self._puts(tenant).limit(1)).one_or_none()
        return None if row is None else self._put(row)

    def tenants(self) -> tuple[str, ...]:
        with self._engine.connect() as connection:
            return tuple(
                connection.execute(
                    sa.select(in_force.c.tenant)
                    .distinct()
                    .order_by(in_force.c.tenant)
                ).scalars()
            )

    @staticmethod
    def _puts(tenant: str) -> sa.Select[str, str, str, datetime, str]:
        """Each time a deployment was put in force for the tenant, the
        latest first."""
        return (
            sa.select(
                in_force.c.repository,
                in_force.c.commit,
                deployments.c.content_hash,
                in_force.c.put_at,
                in_force.c.tenant,
            )
            .join(
                deployments,
                sa.and_(
                    deployments.c.tenant == in_force.c.tenant,
                    deployments.c.repository == in_force.c.repository,
                    deployments.c.commit == in_force.c.commit,
                ),
            )
            .where(in_force.c.tenant == tenant)
            .order_by(in_force.c.id.desc())
        )

    @staticmethod
    def _put(row: sa.Row[str, str, str, datetime, str]) -> PutInForce:
        repository, commit, content_hash, at, tenant = row
        return PutInForce(
            repository=repository,
            commit=commit,
            content_hash=content_hash,
            at=at,
            tenant=tenant,
        )

    @staticmethod
    def _read(
        connection: sa.Connection, tenant: str, repository: str, commit: str
    ) -> PolicyDeployment:
        rows = connection.execute(
            sa.select(files.c.path, files.c.text)
            .where(
                files.c.tenant == tenant,
                files.c.repository == repository,
                files.c.commit == commit,
            )
            .order_by(files.c.path)
        )
        return PolicyDeployment(
            repository=repository,
            commit=commit,
            files=tuple(DeployedFile(path=p, text=t) for p, t in rows),
            tenant=tenant,
        )
