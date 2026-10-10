"""Which profile a repository is bound to, in Postgres.

One row per repository, because a repository is bound to one profile. A
repository with no row is observed, which is the default a deployment
runs until somebody decides otherwise.

The table definition mirrors the script that creates it.
"""

import sqlalchemy as sa

from bugflow.review.domain.models.enforcement import (
    OBSERVE,
    PROFILES,
    EnforcementProfile,
)
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()

repository_enforcement = sa.Table(
    "repository_enforcement",
    metadata,
    sa.Column("forge", sa.Text, primary_key=True),
    sa.Column("repo", sa.Text, primary_key=True),
    sa.Column("profile", sa.Text, nullable=False),
    sa.Column(
        "declared_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)


class SqlAlchemyEnforcement:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def profile_for(self, forge: str, repo: str) -> EnforcementProfile:
        query = sa.select(repository_enforcement.c.profile).where(
            repository_enforcement.c.forge == forge,
            repository_enforcement.c.repo == repo,
        )
        with self._engine.connect() as connection:
            name = connection.execute(query).scalar_one_or_none()
        # A name no profile answers to reads as observed rather than
        # stopping the worker: a deployment that renames a profile
        # should go quiet rather than refuse to review.
        return PROFILES.get(name or "", OBSERVE)

    def bindings(self) -> dict[tuple[str, str], EnforcementProfile]:
        query = sa.select(
            repository_enforcement.c.forge,
            repository_enforcement.c.repo,
            repository_enforcement.c.profile,
        ).order_by(
            repository_enforcement.c.forge, repository_enforcement.c.repo
        )
        with self._engine.connect() as connection:
            return {
                (forge, repo): PROFILES[profile]
                for forge, repo, profile in connection.execute(query)
                if profile in PROFILES
            }

    def bind(self, forge: str, repo: str, profile: EnforcementProfile) -> None:
        """Bind the repository, replacing whatever it was bound to."""
        with self._engine.begin() as connection:
            connection.execute(
                sa.delete(repository_enforcement).where(
                    repository_enforcement.c.forge == forge,
                    repository_enforcement.c.repo == repo,
                )
            )
            connection.execute(
                sa.insert(repository_enforcement).values(
                    forge=forge, repo=repo, profile=profile.name
                )
            )
