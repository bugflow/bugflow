"""Stored exchanges are refused when they exceed the read allowance."""

from typing import Any

import pytest
import sqlalchemy as sa

from bugflow.review.domain.errors import ExchangeNotFoundError
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.infrastructure.sqlalchemy_judge_archive import (
    SqlAlchemyJudgeArchive,
)
from bugflow.shared.domain.errors import ContentTooLargeError


@pytest.fixture(params=["memory", "postgres"])
def archive(
    request: pytest.FixtureRequest,
) -> InMemoryJudgeArchive | SqlAlchemyJudgeArchive:
    if request.param == "memory":
        return InMemoryJudgeArchive()
    return SqlAlchemyJudgeArchive(request.getfixturevalue("database_url"))


def test_an_exchange_read_charges_bytes_and_refuses_a_smaller_allowance(
    archive: InMemoryJudgeArchive | SqlAlchemyJudgeArchive,
) -> None:
    exchange = JudgeExchange(
        request={"text": "é漢" * 400}, response={"ok": True}
    )
    identity = archive.put(exchange)
    found, size = archive.get_bounded(identity, 100_000)
    assert found == exchange
    assert size > len(exchange.request["text"])
    assert archive.get_bounded(identity, size) == (found, size)
    with pytest.raises(ContentTooLargeError):
        archive.get_bounded(identity, size - 1)
    assert archive.get(identity) == exchange


def test_no_allowance_does_not_make_absent_content_oversized(
    archive: InMemoryJudgeArchive | SqlAlchemyJudgeArchive,
) -> None:
    with pytest.raises(ExchangeNotFoundError):
        archive.get_bounded("missing", 0)


def test_postgres_suppresses_both_exchange_payloads_before_transfer(
    database_url: str, engine: sa.Engine
) -> None:
    archive = SqlAlchemyJudgeArchive(database_url)
    identity = archive.put(
        JudgeExchange(
            request={"prompt": "é漢" * 10000},
            response={"answer": "é漢" * 10000},
        )
    )
    queries: list[tuple[str, Any]] = []

    def recorded(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        queries.append((statement, parameters))

    sa.event.listen(archive._engine, "after_cursor_execute", recorded)
    try:
        with pytest.raises(ContentTooLargeError):
            archive.get_bounded(identity, 4096)
    finally:
        sa.event.remove(archive._engine, "after_cursor_execute", recorded)
    assert len(queries) == 1
    # Re-execute the adapter's actual statement to inspect the wire result.
    # An exception raised after fetching full content would fail this check.
    statement, parameters = queries[0]
    with engine.connect() as connection:
        row = connection.exec_driver_sql(statement, parameters).one()
    assert row.bytes > 4096
    assert row.request is None
    assert row.response is None
