"""What each gnome does on each repository, in Postgres (ADR 008).

One row of ``gnome_setting`` for each repository and gnome, keyed by
the repository's row (ADR 005), so a renamed repository keeps its
settings. A repository and gnome with no row are ``off``.

Each change is a ``gnome.set`` fact in the policy journal, and its typed
row is ``gnome_setting_change`` (ADR 007), which ``UNPACKERS`` writes in
the envelope's transaction.

The table definitions mirror the script that creates them.
"""

from collections.abc import Callable, Mapping
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert

from bugflow.review.domain.models.gnome_setting import (
    Behaviour,
    GnomeSetting,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.sqlalchemy_entities import (
    forge,
    repository,
    resolve_repository,
)

metadata = sa.MetaData()

gnome_setting = sa.Table(
    "gnome_setting",
    metadata,
    sa.Column(
        "repository_id",
        sa.BigInteger,
        sa.ForeignKey("repository.id"),
        primary_key=True,
    ),
    # The reviewer's agent id.
    sa.Column("gnome", sa.Text, primary_key=True),
    sa.Column("behaviour", sa.Text, nullable=False),
    sa.Column("profile", sa.Text, nullable=False),
    sa.Column("set_by", sa.Text, nullable=False),
    sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint(
        "behaviour IN ('off', 'observe', 'advise', 'gate')",
        name="gnome_setting_behaviour_check",
    ),
)

gnome_setting_change = sa.Table(
    "gnome_setting_change",
    metadata,
    sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey("policy_journal.event_id"),
        primary_key=True,
    ),
    sa.Column("gnome", sa.Text, nullable=False),
    sa.Column("behaviour", sa.Text, nullable=False),
    sa.Column("profile", sa.Text, nullable=False),
    sa.Column("set_by", sa.Text, nullable=False),
    # What it replaced, null where the gnome had no setting.
    sa.Column("was_behaviour", sa.Text),
    sa.Column("was_profile", sa.Text),
)


def _setting(row: Any) -> GnomeSetting:
    return GnomeSetting(
        forge=row.forge,
        repo=row.repo,
        gnome=row.gnome,
        behaviour=cast(Behaviour, row.behaviour),
        profile=row.profile,
        set_by=row.set_by,
        set_at=row.set_at,
    )


_SELECT = (
    sa.select(
        forge.c.name.label("forge"),
        repository.c.name.label("repo"),
        gnome_setting.c.gnome,
        gnome_setting.c.behaviour,
        gnome_setting.c.profile,
        gnome_setting.c.set_by,
        gnome_setting.c.set_at,
    )
    .select_from(
        gnome_setting.join(
            repository, repository.c.id == gnome_setting.c.repository_id
        ).join(forge, forge.c.id == repository.c.forge_id)
    )
    .order_by(forge.c.name, repository.c.name, gnome_setting.c.gnome)
)


class SqlAlchemyGnomeSettings:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def settings_of(
        self, forge_name: str, repo: str
    ) -> tuple[GnomeSetting, ...]:
        query = _SELECT.where(
            forge.c.name == forge_name, repository.c.name == repo
        )
        with self._engine.connect() as connection:
            return tuple(_setting(row) for row in connection.execute(query))

    def settings(self) -> tuple[GnomeSetting, ...]:
        with self._engine.connect() as connection:
            return tuple(_setting(row) for row in connection.execute(_SELECT))

    def save(self, setting: GnomeSetting) -> None:
        if setting.set_at is None:
            raise ValueError("a setting that is saved says when it was set")
        with self._engine.begin() as connection:
            repository_id = resolve_repository(
                connection, setting.forge, setting.repo, setting.set_at
            )
            values = {
                "behaviour": setting.behaviour,
                "profile": setting.profile,
                "set_by": setting.set_by,
                "set_at": setting.set_at,
            }
            connection.execute(
                insert(gnome_setting)
                .values(
                    repository_id=repository_id, gnome=setting.gnome, **values
                )
                .on_conflict_do_update(
                    index_elements=["repository_id", "gnome"], set_=values
                )
            )


def unpack_setting(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    connection.execute(
        insert(gnome_setting_change)
        .values(
            event_id=entry.event_id,
            gnome=entry.agent_id,
            behaviour=p["behaviour"],
            profile=p["profile"],
            set_by=p["set_by"],
            was_behaviour=p.get("was_behaviour"),
            was_profile=p.get("was_profile"),
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
    )


Unpacker = Callable[[sa.Connection, JournalEntry], None]

#: What writes a setting's typed row, by event type.
UNPACKERS: Mapping[str, Unpacker] = {"gnome.set": unpack_setting}
