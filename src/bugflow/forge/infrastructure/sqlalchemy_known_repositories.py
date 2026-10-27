"""The repositories this server knows of, in Postgres: the rows of ADR
005's ``repository`` table, with the forge's key and whether the
repository is archived (ADR 008).

``repository_finding`` is the typed table of the ``repository.found``
fact (ADR 007), which ``UNPACKERS`` writes in the envelope's
transaction.

The table definitions mirror the scripts that create them.
"""

from collections.abc import Callable, Collection, Mapping
from dataclasses import replace
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert

from bugflow.forge.domain.models.forge_repository import (
    KnownRepository,
    ListedRepository,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.sqlalchemy_entities import (
    forge,
    repository,
    repository_name,
    resolve_repository,
)

metadata = sa.MetaData()

repository_finding = sa.Table(
    "repository_finding",
    metadata,
    sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey("forge_journal.event_id"),
        primary_key=True,
    ),
    sa.Column("change", sa.Text, nullable=False),
    sa.Column("forge_key", sa.Text, nullable=False),
    sa.Column("archived", sa.Boolean, nullable=False),
    # The name it had before, for a rename.
    sa.Column("was_name", sa.Text),
)


class SqlAlchemyKnownRepositories:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def known(
        self, forge_name: str, owner: str, forge_keys: Collection[str] = ()
    ) -> list[KnownRepository]:
        query = (
            sa.select(
                repository.c.name,
                repository.c.forge_key,
                repository.c.archived,
            )
            .select_from(
                repository.join(forge, forge.c.id == repository.c.forge_id)
            )
            .where(
                forge.c.name == forge_name,
                sa.or_(
                    sa.func.lower(repository.c.name).startswith(
                        f"{owner.lower()}/"
                    ),
                    repository.c.forge_key.in_(list(forge_keys)),
                ),
            )
            .order_by(repository.c.name)
        )
        with self._engine.connect() as connection:
            return [
                KnownRepository(
                    forge=forge_name,
                    name=row.name,
                    forge_key=row.forge_key,
                    archived=row.archived,
                )
                for row in connection.execute(query)
            ]

    def keep(self, listed: ListedRepository) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            forge_id = connection.execute(
                sa.select(forge.c.id).where(forge.c.name == listed.forge)
            ).scalar_one_or_none()
            keyed = (
                connection.execute(
                    sa.select(repository.c.id, repository.c.name).where(
                        repository.c.forge_id == forge_id,
                        repository.c.forge_key == listed.forge_key,
                    )
                ).first()
                if forge_id is not None
                else None
            )
            if keyed is not None and keyed.name != listed.name:
                named = connection.execute(
                    sa.select(repository.c.id).where(
                        repository.c.forge_id == forge_id,
                        repository.c.name == listed.name,
                    )
                ).scalar_one_or_none()
                if named is not None:
                    # Another row already holds the new name, made by the
                    # journal before discovery saw the rename. Both rows
                    # stay; the key moves to the one by the new name, so
                    # the rename is recorded once.
                    connection.execute(
                        sa.update(repository)
                        .where(repository.c.id == keyed.id)
                        .values(forge_key=None)
                    )
                    connection.execute(
                        sa.update(repository)
                        .where(repository.c.id == named)
                        .values(
                            forge_key=listed.forge_key,
                            archived=listed.archived,
                        )
                    )
                    return
                connection.execute(
                    sa.update(repository)
                    .where(repository.c.id == keyed.id)
                    .values(name=listed.name)
                )
                connection.execute(
                    insert(repository_name)
                    .values(
                        repository_id=keyed.id,
                        name=listed.name,
                        first_seen=now,
                    )
                    .on_conflict_do_nothing()
                )
                repository_id = keyed.id
            elif keyed is not None:
                repository_id = keyed.id
            else:
                repository_id = resolve_repository(
                    connection, listed.forge, listed.name, now
                )
            connection.execute(
                sa.update(repository)
                .where(repository.c.id == repository_id)
                .values(forge_key=listed.forge_key, archived=listed.archived)
            )


class InMemoryKnownRepositories:
    """The same, held in memory, for tests."""

    def __init__(self, *known: KnownRepository) -> None:
        self.held: list[KnownRepository] = list(known)

    def known(
        self, forge_name: str, owner: str, forge_keys: Collection[str] = ()
    ) -> list[KnownRepository]:
        return [
            one
            for one in self.held
            if one.forge == forge_name
            and (
                one.name.lower().startswith(f"{owner.lower()}/")
                or one.forge_key in forge_keys
            )
        ]

    def keep(self, listed: ListedRepository) -> None:
        keyed = next(
            (one for one in self.held if one.forge_key == listed.forge_key),
            None,
        )
        named = next(
            (one for one in self.held if one.name == listed.name), None
        )
        if keyed is not None and named is not None and keyed != named:
            self.held.remove(keyed)
            self.held.append(replace(keyed, forge_key=None))
        held = named or keyed
        if held is not None:
            self.held.remove(held)
        self.held.append(
            KnownRepository(
                forge=listed.forge,
                name=listed.name,
                forge_key=listed.forge_key,
                archived=listed.archived,
            )
        )


def unpack_finding(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    connection.execute(
        insert(repository_finding)
        .values(
            event_id=entry.event_id,
            change=p["change"],
            forge_key=p["forge_key"],
            archived=p["archived"],
            was_name=p.get("was_name"),
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
    )


Unpacker = Callable[[sa.Connection, JournalEntry], None]

#: What writes a finding's typed row, by event type.
UNPACKERS: Mapping[str, Unpacker] = {"repository.found": unpack_finding}
