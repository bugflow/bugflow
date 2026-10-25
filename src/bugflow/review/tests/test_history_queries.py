"""History readers preserve scope, bounds and stored evidence."""

from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import sqlalchemy as sa

from bugflow.review.domain.errors import HistoryTooLargeError
from bugflow.review.domain.models.history import (
    HistoryLimits,
    HistoryScope,
    StoredReviewEvent,
)
from bugflow.review.domain.models.review_entry import ReviewEntry, from_payload
from bugflow.review.domain.services.journal import HistoryService
from bugflow.review.infrastructure.in_memory_history import InMemoryHistory
from bugflow.review.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries,
)
from bugflow.review.infrastructure.sqlalchemy_review_facts import (
    UNPACKERS as REVIEW_UNPACKERS,
)
from bugflow.review.tests.payloads import whole
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    SqlAlchemyJournal,
    table_for,
)

AT = datetime(2030, 1, 1, tzinfo=UTC)
LIMITS = HistoryLimits()
ReaderFactory = Callable[[list[StoredReviewEvent]], HistoryService]


def event(
    scope: HistoryScope, *, number: int = 1, run: str = "run"
) -> StoredReviewEvent:
    return StoredReviewEvent(
        entry=ReviewEntry(
            event_id=uuid4(),
            occurred_at=AT,
            event_type="judge.invoked",
            forge=scope.forge,
            repo=scope.repo,
            pr_number=number,
            commit_sha="head",
            corpus_version="corpus",
            workflow_id="workflow",
            run_id=run,
            payload=whole(
                "judge.invoked", policy_id="P-01", status="unavailable"
            ),
            build="build",
        ),
        recorded_at=AT,
        policy_repository="policies/repo",
        policy_commit="policy-commit",
        policy_content="policy-content",
    )


def with_payload(
    stored: StoredReviewEvent,
    payload: dict[str, Any],
    event_type: str | None = None,
) -> StoredReviewEvent:
    """The event as written with another payload, and another type where
    one is given."""
    return replace(
        stored,
        entry=replace(
            stored.entry,
            payload=payload,
            fact=None,
            event_type=event_type or stored.entry.event_type,
        ),
    )


def read(stored: StoredReviewEvent) -> StoredReviewEvent:
    """The event as a reader returns it: the fact from its table, the
    review journal's payload empty."""
    return replace(stored, entry=from_payload(stored.entry))


def columns(stored: StoredReviewEvent) -> dict[str, Any]:
    values = asdict(stored.entry)
    values.pop("origin")  # Provenance is stored in the association table.
    values.pop("origin_asserted")
    values.pop("fact")  # Read from the fact's table, not a column.
    if "payload" not in table_for(stored.entry.event_type).c:
        values.pop("payload")
    return values | {
        "recorded_at": stored.recorded_at,
        "policy_repository": stored.policy_repository,
        "policy_commit": stored.policy_commit,
        "policy_content": stored.policy_content,
    }


@pytest.fixture
def scope() -> HistoryScope:
    return HistoryScope(
        forge="github", repo=f"org/history-{uuid4().hex}", pr_numbers=(1, 2)
    )


@pytest.fixture(params=["memory", "postgres"])
def reader_factory(request: pytest.FixtureRequest) -> ReaderFactory:
    if request.param == "memory":
        return InMemoryHistory
    database_url: str = request.getfixturevalue("database_url")
    engine: sa.Engine = request.getfixturevalue("engine")

    def make(events: list[StoredReviewEvent]) -> HistoryService:
        from sqlalchemy.dialects.postgresql import insert

        if events:
            with engine.begin() as connection:
                for event in events:
                    connection.execute(
                        insert(table_for(event.entry.event_type))
                        .values(columns(event))
                        .on_conflict_do_nothing(index_elements=["event_id"])
                    )
                    # The fact's row, as the journal adapter writes it.
                    unpack = REVIEW_UNPACKERS.get(event.entry.event_type)
                    if unpack is not None:
                        unpack(connection, event.entry)
        return SqlAlchemyJournalQueries(database_url)

    return make


def test_scope_includes_forge_repository_pr_and_optional_run(
    reader_factory: ReaderFactory, scope: HistoryScope
) -> None:
    first, second = event(scope), event(scope, number=2, run="another")
    others = [
        event(replace(scope, forge="forgejo")),
        event(replace(scope, repo=f"other/{uuid4().hex}")),
        event(scope, number=3),
    ]
    reader = reader_factory([first, second, *others])

    assert {
        e.entry.event_id for e in reader.entries_for_history(scope, LIMITS)
    } == {first.entry.event_id, second.entry.event_id}
    selected = replace(
        scope, correlation=Correlation(workflow_id="workflow", run_id="run")
    )
    assert reader.entries_for_history(selected, LIMITS) == (read(first),)
    assert (
        reader.entries_for_history(
            replace(scope, repo=f"absent/{uuid4().hex}"), LIMITS
        )
        == ()
    )


def test_equal_times_are_ordered_by_event_id_and_duplicates_keep_first(
    reader_factory: ReaderFactory, scope: HistoryScope
) -> None:
    first = event(scope)
    second = replace(first, entry=replace(first.entry, event_id=uuid4()))
    earlier = replace(event(scope), recorded_at=AT - timedelta(seconds=1))
    oldest = replace(
        event(scope),
        entry=replace(event(scope).entry, occurred_at=AT - timedelta(days=1)),
    )
    duplicate = with_payload(first, whole("judge.invoked", later=True))
    reader = reader_factory([second, first, earlier, oldest, duplicate])

    assert reader.entries_for_history(scope, LIMITS) == (
        read(oldest),
        read(earlier),
        *sorted((read(first), read(second)), key=lambda e: e.entry.event_id),
    )


def test_the_event_bound_refuses_the_whole_request(
    reader_factory: ReaderFactory, scope: HistoryScope
) -> None:
    events = [event(scope), event(scope)]
    reader = reader_factory(events)
    assert (
        len(reader.entries_for_history(scope, HistoryLimits(max_events=2)))
        == 2
    )
    with pytest.raises(HistoryTooLargeError, match="event limit"):
        reader.entries_for_history(scope, HistoryLimits(max_events=1))


@pytest.mark.parametrize("large_field", ["payload", "provenance"])
def test_byte_guard_counts_multibyte_payloads_and_provenance(
    reader_factory: ReaderFactory, scope: HistoryScope, large_field: str
) -> None:
    one = event(scope)
    if large_field == "payload":
        # A journal that keeps its payload, since the review's does not.
        one = with_payload(one, {"text": "é" * 4096}, "stocktake.taken")
    else:
        one = replace(one, policy_repository="é" * 4096)
    reader = reader_factory([one])
    with pytest.raises(HistoryTooLargeError, match="byte limit"):
        reader.entries_for_history(scope, HistoryLimits(max_bytes=4096))
    assert reader.entries_for_history(scope, LIMITS) == (read(one),)


def test_missing_deployment_stamps_remain_missing(
    reader_factory: ReaderFactory, scope: HistoryScope
) -> None:
    one = replace(
        event(scope),
        policy_repository=None,
        policy_commit=None,
        policy_content=None,
    )
    assert reader_factory([one]).entries_for_history(scope, LIMITS) == (
        read(one),
    )


def test_postgres_returns_the_writers_provenance(
    database_url: str, scope: HistoryScope
) -> None:
    one = event(scope)
    SqlAlchemyJournal(
        database_url,
        build="actual-build",
        policy_repository="actual/repo",
        policy_commit="actual-commit",
        policy_content="actual-content",
        unpackers=REVIEW_UNPACKERS,
    ).append([one.entry])
    (read,) = SqlAlchemyJournalQueries(database_url).entries_for_history(
        scope, LIMITS
    )
    assert read.recorded_at is not None
    assert read.entry.build == "actual-build"
    assert (
        read.policy_repository,
        read.policy_commit,
        read.policy_content,
    ) == ("actual/repo", "actual-commit", "actual-content")


def test_preflight_and_fetch_share_a_snapshot_despite_a_late_commit(
    database_url: str, engine: sa.Engine, scope: HistoryScope
) -> None:
    one, late = event(scope), event(scope)
    SqlAlchemyJournal(database_url, unpackers=REVIEW_UNPACKERS).append(
        [one.entry]
    )
    reader = SqlAlchemyJournalQueries(database_url)
    statements: list[str] = []
    with engine.connect() as writer:
        transaction = writer.begin()
        # This transaction's recorded_at precedes the history read.
        values = asdict(late.entry)
        values.pop("origin")
        values.pop("origin_asserted")
        values.pop("fact")
        values.pop("payload")  # The review journal has no column for it.
        writer.execute(
            sa.insert(table_for(late.entry.event_type)).values(values)
        )

        def after_query(
            connection: Any,
            cursor: Any,
            statement: str,
            parameters: Any,
            context: Any,
            executemany: bool,
        ) -> None:
            statements.append(statement)
            if len(statements) == 1:
                transaction.commit()

        sa.event.listen(reader._engine, "after_cursor_execute", after_query)
        try:
            found = reader.entries_for_history(
                scope, HistoryLimits(max_events=1)
            )
        finally:
            sa.event.remove(
                reader._engine, "after_cursor_execute", after_query
            )
            if transaction.is_active:
                transaction.rollback()
    assert [e.entry.event_id for e in found] == [one.entry.event_id]
    # The preflight, the fetch, and the reads of the facts' tables, all
    # in the one transaction: the first committed the late row, and none
    # of the others saw it.
    assert len(statements) > 2
    assert len(reader.entries_for_history(scope, LIMITS)) == 2


def test_oversized_payload_is_refused_before_payload_fetch(
    database_url: str, scope: HistoryScope
) -> None:
    one = event(scope)
    # A journal that keeps its payload, since the review's does not.
    SqlAlchemyJournal(database_url, unpackers=REVIEW_UNPACKERS).append(
        [
            replace(
                one.entry,
                event_type="stocktake.taken",
                payload={"text": "x" * 10000},
                fact=None,
            )
        ]
    )
    reader = SqlAlchemyJournalQueries(database_url)
    statements: list[str] = []

    def after_query(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    sa.event.listen(reader._engine, "after_cursor_execute", after_query)
    try:
        with pytest.raises(HistoryTooLargeError, match="byte limit"):
            reader.entries_for_history(scope, HistoryLimits(max_bytes=4096))
    finally:
        sa.event.remove(reader._engine, "after_cursor_execute", after_query)
    assert len(statements) == 1
