"""The store of block upload records, in Postgres.

One row for each block uploaded to each ledger. Uploading the same block
again updates the row's time. The time is what lets a block that no event
ever referred to be found later.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from bugflow.archive.domain.models.block_put import BlockPut
from bugflow.shared.infrastructure.database import engine_url

metadata = sa.MetaData()

archive_block_puts = sa.Table(
    "archive_block_puts",
    metadata,
    sa.Column("ledger_id", sa.Text, primary_key=True),
    sa.Column("cid", sa.Text, primary_key=True),
    sa.Column("size", sa.Integer, nullable=False),
    sa.Column("caller", sa.Text, nullable=False),
    sa.Column("new", sa.Boolean, nullable=False),
    sa.Column(
        "put_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    ),
)


class SqlAlchemyBlockPuts:
    def __init__(self, database_url: str) -> None:
        self._engine = sa.create_engine(
            engine_url(database_url), pool_pre_ping=True
        )

    def record(self, put: BlockPut) -> None:
        statement = (
            insert(archive_block_puts)
            .values(
                ledger_id=put.ledger_id,
                cid=put.cid,
                size=put.size,
                caller=put.caller,
                new=put.new,
            )
            .on_conflict_do_update(
                index_elements=["ledger_id", "cid"],
                set_={"caller": put.caller, "put_at": sa.func.now()},
            )
        )
        with self._engine.begin() as connection:
            connection.execute(statement)

    def of_ledger(self, ledger_id: str) -> list[BlockPut]:
        query = (
            sa.select(archive_block_puts)
            .where(archive_block_puts.c.ledger_id == ledger_id)
            .order_by(archive_block_puts.c.cid)
        )
        with self._engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return [
            BlockPut(
                ledger_id=row["ledger_id"],
                cid=row["cid"],
                size=row["size"],
                caller=row["caller"],
                new=row["new"],
            )
            for row in rows
        ]
