"""Tests of the Postgres store of block upload records, against a real
database.

Skipped unless DATABASE_URL names a Postgres server.
"""

import uuid

import sqlalchemy as sa

from bugflow.archive.domain.models.block_put import BlockPut
from bugflow.archive.infrastructure.sqlalchemy_block_puts import (
    SqlAlchemyBlockPuts,
    archive_block_puts,
)


def put(ledger: str, block: str, new: bool = True) -> BlockPut:
    return BlockPut(
        ledger_id=ledger, cid=block, size=5, caller="someone", new=new
    )


def test_a_ledger_s_puts_read_back_by_cid_and_a_second_put_renews(
    engine: sa.Engine, database_url: str
) -> None:
    puts = SqlAlchemyBlockPuts(database_url)
    ledger, other = str(uuid.uuid4()), str(uuid.uuid4())
    puts.record(put(ledger, "bafkreib"))
    puts.record(put(ledger, "bafkreia"))
    puts.record(put(other, "bafkreia"))
    with engine.connect() as connection:
        first = connection.execute(
            sa.select(archive_block_puts.c.put_at).where(
                archive_block_puts.c.ledger_id == ledger,
                archive_block_puts.c.cid == "bafkreia",
            )
        ).scalar_one()
    # The same block is uploaded again by a different caller, after the store
    # has it. The record's time is updated, and it still says the block was new
    # the first time.
    puts.record(
        BlockPut(
            ledger_id=ledger,
            cid="bafkreia",
            size=5,
            caller="another",
            new=False,
        )
    )
    with engine.connect() as connection:
        renewed = connection.execute(
            sa.select(archive_block_puts.c.put_at).where(
                archive_block_puts.c.ledger_id == ledger,
                archive_block_puts.c.cid == "bafkreia",
            )
        ).scalar_one()
    assert renewed >= first
    assert puts.of_ledger(ledger) == [
        BlockPut(
            ledger_id=ledger,
            cid="bafkreia",
            size=5,
            caller="another",
            new=True,
        ),
        put(ledger, "bafkreib"),
    ]
    assert puts.of_ledger(str(uuid.uuid4())) == []
