"""The deployments this server was sent, in Postgres.

Three tables, which is this adapter's choice: a deployment by the names
it was sent under, its files one row each, and one row for each time a
deployment was put in force. The last of those is only added to, so
what was in force on a day stays answerable. The table definitions
mirror the script that creates them.
"""

from datetime import datetime

import sqlalchemy as sa

from bugflow.method.domain.errors import PolicyDeploymentConflictError
from bugflow.method.domain.models.policy_deployment import (
    DeployedFile,
    PolicyDeployment,
    PutInForce,
)
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()

deployments = sa.Table(
    "policy_deployments",
    metadata,
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
    "policy_deployment_files",
    metadata,
    sa.Column("repository", sa.Text, primary_key=True),
    sa.Column("commit", sa.Text, primary_key=True),
    sa.Column("path", sa.Text, primary_key=True),
    sa.Column("text", sa.Text, nullable=False),
    sa.ForeignKeyConstraint(
        ["repository", "commit"],
        ["policy_deployments.repository", "policy_deployments.commit"],
    ),
)

in_force = sa.Table(
    "policy_deployments_in_force",
    metadata,
    sa.Column("id", sa.BigInteger, sa.Identity(), primary_key=True),
    sa.Column("repository", sa.Text, nullable=False),
    sa.Column("commit", sa.Text, nullable=False),
    sa.Column(
        "put_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.ForeignKeyConstraint(
        ["repository", "commit"],
        ["policy_deployments.repository", "policy_deployments.commit"],
    ),
)


class SqlAlchemyPolicyDeployments:
    """Implements ``PolicyDeploymentRepository`` over Postgres."""

    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def deploy(self, deployment: PolicyDeployment) -> bool:
        """Store and put in force in one transaction, so a deployment is
        never in force with only some of its files."""
        repository, commit = deployment.repository, deployment.commit
        with self._engine.begin() as connection:
            earlier = connection.execute(
                sa.select(deployments.c.content_hash).where(
                    deployments.c.repository == repository,
                    deployments.c.commit == commit,
                )
            ).scalar_one_or_none()
            if earlier is None:
                connection.execute(
                    sa.insert(deployments).values(
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
            latest = connection.execute(self._latest()).one_or_none()
            if latest is not None and tuple(latest) == (repository, commit):
                return False
            connection.execute(
                sa.insert(in_force).values(
                    repository=repository, commit=commit
                )
            )
            return True

    def in_force(self) -> PolicyDeployment | None:
        with self._engine.connect() as connection:
            latest = connection.execute(self._latest()).one_or_none()
            if latest is None:
                return None
            return self._read(connection, latest[0], latest[1])

    def held(self, repository: str, commit: str) -> PolicyDeployment | None:
        with self._engine.connect() as connection:
            known = connection.execute(
                sa.select(deployments.c.commit).where(
                    deployments.c.repository == repository,
                    deployments.c.commit == commit,
                )
            ).one_or_none()
            if known is None:
                return None
            return self._read(connection, repository, commit)

    def last_put_in_force(self) -> PutInForce | None:
        with self._engine.connect() as connection:
            row = connection.execute(self._puts().limit(1)).one_or_none()
        return None if row is None else self._put(row)

    def history(self) -> list[PutInForce]:
        with self._engine.connect() as connection:
            return [self._put(row) for row in connection.execute(self._puts())]

    @staticmethod
    def _puts() -> sa.Select[str, str, str, datetime]:
        """Each time a deployment was put in force, the latest first."""
        return (
            sa.select(
                in_force.c.repository,
                in_force.c.commit,
                deployments.c.content_hash,
                in_force.c.put_at,
            )
            .join(
                deployments,
                sa.and_(
                    deployments.c.repository == in_force.c.repository,
                    deployments.c.commit == in_force.c.commit,
                ),
            )
            .order_by(in_force.c.id.desc())
        )

    @staticmethod
    def _put(row: sa.Row[str, str, str, datetime]) -> PutInForce:
        repository, commit, content_hash, at = row
        return PutInForce(
            repository=repository,
            commit=commit,
            content_hash=content_hash,
            at=at,
        )

    @staticmethod
    def _latest() -> sa.Select[str, str]:
        return (
            sa.select(in_force.c.repository, in_force.c.commit)
            .order_by(in_force.c.id.desc())
            .limit(1)
        )

    @staticmethod
    def _read(
        connection: sa.Connection, repository: str, commit: str
    ) -> PolicyDeployment:
        rows = connection.execute(
            sa.select(files.c.path, files.c.text)
            .where(files.c.repository == repository, files.c.commit == commit)
            .order_by(files.c.path)
        )
        return PolicyDeployment(
            repository=repository,
            commit=commit,
            files=tuple(DeployedFile(path=p, text=t) for p, t in rows),
        )
