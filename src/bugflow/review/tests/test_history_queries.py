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
from bugflow.review.domain.services.journal import HistoryService
from bugflow.review.infrastructure.in_memory_history import InMemoryHistory
from bugflow.review.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.infrastructure.sqlalchemy_journal import (
    SqlAlchemyJournal,
    journal,
)

AT = datetime(2030, 1, 1, tzinfo=UTC)
LIMITS = HistoryLimits()
ReaderFactory = Callable[[list[StoredReviewEvent]], HistoryService]


def event(
    scope: HistoryScope, *, number: int = 1, run: str = "run"
) -> StoredReviewEvent:
    return StoredReviewEvent(
        entry=JournalEntry(
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
            payload={"policy_id": "P-01", "status": "unavailable"},
            build="build",
        ),
        recorded_at=AT,
        policy_repository="policies/repo",
        policy_commit="policy-commit",
        policy_content="policy-content",
    )


def columns(stored: StoredReviewEvent) -> dict[str, Any]:
    values = asdict(stored.entry)
    values.pop("origin")  # Provenance is stored in the association table.
    values.pop("origin_asserted")
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
                connection.execute(
                    insert(journal)
                    .values([columns(e) for e in events])
                    .on_conflict_do_nothing(index_elements=["event_id"])
                )
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
    assert reader.entries_for_history(selected, LIMITS) == (first,)
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
    duplicate = replace(
        first, entry=replace(first.entry, payload={"later": True})
    )
    reader = reader_factory([second, first, earlier, oldest, duplicate])

    assert reader.entries_for_history(scope, LIMITS) == (
        oldest,
        earlier,
        *sorted((first, second), key=lambda e: e.entry.event_id),
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
        one = replace(
            one, entry=replace(one.entry, payload={"text": "é" * 4096})
        )
    else:
        one = replace(one, policy_repository="é" * 4096)
    reader = reader_factory([one])
    with pytest.raises(HistoryTooLargeError, match="byte limit"):
        reader.entries_for_history(scope, HistoryLimits(max_bytes=4096))
    assert reader.entries_for_history(scope, LIMITS) == (one,)


def test_missing_deployment_stamps_remain_missing(
    reader_factory: ReaderFactory, scope: HistoryScope
) -> None:
    one = replace(
        event(scope),
        policy_repository=None,
        policy_commit=None,
        policy_content=None,
    )
    assert reader_factory([one]).entries_for_history(scope, LIMITS) == (one,)


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
    SqlAlchemyJournal(database_url).append([one.entry])
    reader = SqlAlchemyJournalQueries(database_url)
    statements: list[str] = []
    with engine.connect() as writer:
        transaction = writer.begin()
        # This transaction's recorded_at precedes the history read.
        values = asdict(late.entry)
        values.pop("origin")
        values.pop("origin_asserted")
        writer.execute(sa.insert(journal).values(values))

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
    assert len(statements) == 2
    assert len(reader.entries_for_history(scope, LIMITS)) == 2


def test_oversized_payload_is_refused_before_payload_fetch(
    database_url: str, scope: HistoryScope
) -> None:
    one = event(scope)
    SqlAlchemyJournal(database_url).append(
        [replace(one.entry, payload={"text": "x" * 10000})]
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
