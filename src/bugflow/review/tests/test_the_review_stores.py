"""Tests of the stores of judge exchanges and write-ups.

Each test runs twice: against the in-memory store and against the
Postgres one. The two must behave the same. The Postgres half is
skipped unless DATABASE_URL names a Postgres server.

The database is shared by the tests in a session, so each test stores
content of its own.
"""

from uuid import uuid4

import pytest

from bugflow.review.domain.errors import (
    ExchangeNotFoundError,
    WriteUpNotFoundError,
)
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.domain.models.write_up import WriteUp
from bugflow.review.domain.repositories.judge_archive import (
    JudgeArchiveRepository,
)
from bugflow.review.domain.repositories.write_up_archive import (
    WriteUpArchiveRepository,
)
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.infrastructure.in_memory_write_up_archive import (
    InMemoryWriteUpArchive,
)
from bugflow.review.infrastructure.sqlalchemy_judge_archive import (
    SqlAlchemyJudgeArchive,
)
from bugflow.review.infrastructure.sqlalchemy_write_up_archive import (
    SqlAlchemyWriteUpArchive,
)
from bugflow.shared.domain.values.correlation import Correlation


@pytest.fixture(params=["memory", "postgres"])
def exchanges(request: pytest.FixtureRequest) -> JudgeArchiveRepository:
    if request.param == "memory":
        return InMemoryJudgeArchive()
    return SqlAlchemyJudgeArchive(request.getfixturevalue("database_url"))


@pytest.fixture(params=["memory", "postgres"])
def write_ups(request: pytest.FixtureRequest) -> WriteUpArchiveRepository:
    if request.param == "memory":
        return InMemoryWriteUpArchive()
    return SqlAlchemyWriteUpArchive(request.getfixturevalue("database_url"))


def an_exchange() -> JudgeExchange:
    return JudgeExchange(
        request={"policy": "P-01", "nonce": uuid4().hex, "n": [1, None]},
        response={"violations": [{"clause": "RULE-1", "quote": "é"}]},
    )


def test_an_exchange_reads_back_as_it_was_stored(
    exchanges: JudgeArchiveRepository,
) -> None:
    exchange = an_exchange()

    exchange_id = exchanges.put(exchange)

    assert exchange_id == exchange.exchange_id
    assert exchanges.get(exchange_id) == exchange


def test_storing_the_same_exchange_twice_gives_the_same_id(
    exchanges: JudgeArchiveRepository,
) -> None:
    exchange = an_exchange()

    assert exchanges.put(exchange) == exchanges.put(exchange)
    assert exchanges.get(exchange.exchange_id) == exchange


def test_an_exchange_that_is_not_stored_is_an_error(
    exchanges: JudgeArchiveRepository,
) -> None:
    with pytest.raises(ExchangeNotFoundError):
        exchanges.get(f"missing-{uuid4().hex}")


def a_write_up(text: str = "I read the diff.") -> WriteUp:
    return WriteUp(
        correlation=Correlation(workflow_id="pr/5", run_id=uuid4().hex),
        agent_id="safety",
        text=text,
    )


def test_a_write_up_reads_back_as_it_was_stored(
    write_ups: WriteUpArchiveRepository,
) -> None:
    write_up = a_write_up()

    write_up_id = write_ups.put(write_up)

    assert write_up_id == write_up.write_up_id
    assert write_ups.get(write_up_id) == write_up


def test_a_second_write_up_for_the_same_run_keeps_the_first(
    write_ups: WriteUpArchiveRepository,
) -> None:
    first = a_write_up("The first text.")
    second = WriteUp(
        correlation=first.correlation,
        agent_id=first.agent_id,
        text="Another text.",
    )

    assert write_ups.put(first) == write_ups.put(second)
    assert write_ups.get(first.write_up_id).text == "The first text."


def test_a_write_up_that_is_not_stored_is_an_error(
    write_ups: WriteUpArchiveRepository,
) -> None:
    with pytest.raises(WriteUpNotFoundError):
        write_ups.get(f"missing/{uuid4().hex}/safety")
