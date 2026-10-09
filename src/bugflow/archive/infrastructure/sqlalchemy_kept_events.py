"""The store of ledger events, in Postgres.

One row for each event, holding its exact bytes. A row is written once and
never updated. The bytes are kept because the next event a client sends is
checked against them.

The journal separately records that each event was accepted.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from bugflow.archive.domain.models.kept_event import KeptEvent
from bugflow.archive.domain.repositories.kept_events import EventTakenError
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()

archive_events = sa.Table(
    "archive_events",
    metadata,
    sa.Column("ledger_id", sa.Text, primary_key=True),
    sa.Column("number", sa.Integer, primary_key=True),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("data", sa.LargeBinary, nullable=False),
    sa.Column("claims", JSONB, nullable=False),
    sa.Column("caller", sa.Text, nullable=False),
    sa.Column(
        "accepted_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)


class SqlAlchemyKeptEvents:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def of_ledger(self, ledger_id: str) -> list[KeptEvent]:
        query = (
            sa.select(archive_events)
            .where(archive_events.c.ledger_id == ledger_id)
            .order_by(archive_events.c.number)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [
            KeptEvent(
                ledger_id=row["ledger_id"],
                number=row["number"],
                name=row["name"],
                data=bytes(row["data"]),
                claims=dict(row["claims"]),
                caller=row["caller"],
            )
            for row in rows
        ]

    def add(self, event: KeptEvent) -> None:
        statement = sa.insert(archive_events).values(
            ledger_id=event.ledger_id,
            number=event.number,
            name=event.name,
            data=event.data,
            claims=event.claims,
            caller=event.caller,
        )
        try:
            with self._engine.begin() as connection:
                connection.execute(statement)
        except sa.exc.IntegrityError as exc:
            raise EventTakenError(
                f"ledger {event.ledger_id} has an event {event.number}"
            ) from exc
