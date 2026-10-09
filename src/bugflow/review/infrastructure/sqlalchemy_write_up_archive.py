"""The store of write-ups in a Postgres table.

A write-up is stored under its workflow run and its agent. The table is
made by the scripts in ``migrations``.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from bugflow.review.domain.errors import WriteUpNotFoundError
from bugflow.review.domain.models.write_up import WriteUp
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()
write_ups = sa.Table(
    "agent_write_ups",
    metadata,
    sa.Column("write_up_id", sa.Text, primary_key=True),
    sa.Column(
        "stored_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
    sa.Column("workflow_id", sa.Text, nullable=False),
    sa.Column("run_id", sa.Text, nullable=False),
    sa.Column("agent_id", sa.Text, nullable=False),
    sa.Column("write_up", sa.Text, nullable=False),
)


class SqlAlchemyWriteUpArchive:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def put(self, write_up: WriteUp) -> str:
        write_up_id = write_up.write_up_id
        statement = (
            insert(write_ups)
            .values(
                write_up_id=write_up_id,
                workflow_id=write_up.correlation.workflow_id,
                run_id=write_up.correlation.run_id,
                agent_id=write_up.agent_id,
                write_up=write_up.text,
            )
            .on_conflict_do_nothing(index_elements=["write_up_id"])
        )
        with self._engine.begin() as connection:
            connection.execute(statement)
        return write_up_id

    def get(self, write_up_id: str) -> WriteUp:
        query = sa.select(
            write_ups.c.workflow_id,
            write_ups.c.run_id,
            write_ups.c.agent_id,
            write_ups.c.write_up,
        ).where(write_ups.c.write_up_id == write_up_id)
        with self._engine.connect() as connection:
            row = connection.execute(query).one_or_none()
        if row is None:
            raise WriteUpNotFoundError(f"no archived write-up {write_up_id}")
        return WriteUp(
            correlation=Correlation(
                workflow_id=row.workflow_id, run_id=row.run_id
            ),
            agent_id=row.agent_id,
            text=row.write_up,
        )
