"""Tests of the Postgres store of ledger events, against a real database.

Skipped unless DATABASE_URL names a Postgres server.
"""

import uuid

import pytest
import sqlalchemy as sa

from bugflow.archive.domain.models.kept_event import KeptEvent
from bugflow.archive.domain.repositories.kept_events import EventTakenError
from bugflow.archive.infrastructure.sqlalchemy_kept_events import (
    SqlAlchemyKeptEvents,
)


def event(ledger: str, number: int, data: bytes = b"{}") -> KeptEvent:
    return KeptEvent(
        ledger_id=ledger,
        number=number,
        name=f"{number:08}-name.json",
        data=data,
        claims={"remote": "git@forge.example:someone/garden.git"},
        caller="someone",
    )


def test_a_ledger_s_events_read_back_in_order_byte_for_byte(
    engine: sa.Engine, database_url: str
) -> None:
    kept = SqlAlchemyKeptEvents(database_url)
    ledger, other = str(uuid.uuid4()), str(uuid.uuid4())
    block = bytes(range(256))
    for added in (event(ledger, 2, block), event(ledger, 1), event(other, 1)):
        kept.add(added)

    assert kept.of_ledger(ledger) == [
        event(ledger, 1),
        event(ledger, 2, block),
    ]
    assert kept.of_ledger(str(uuid.uuid4())) == []


def test_a_second_event_of_a_number_is_refused_and_the_first_stands(
    engine: sa.Engine, database_url: str
) -> None:
    kept = SqlAlchemyKeptEvents(database_url)
    ledger = str(uuid.uuid4())
    kept.add(event(ledger, 1, b"first"))

    with pytest.raises(EventTakenError):
        kept.add(event(ledger, 1, b"second"))

    assert kept.of_ledger(ledger) == [event(ledger, 1, b"first")]
