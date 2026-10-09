"""Tests of the work context's questions of the journal.

Each test runs twice: against the in-memory journal the other tests
use, and against the Postgres adapter. The two must give the same
answers. The Postgres half is skipped unless DATABASE_URL names a
Postgres server.

The database is shared by the tests in a session, so each test uses a
repository and a runner with names of its own.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

import pytest

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal
from bugflow.work.domain.facts import AGENT_DISPATCHED, PR_OBSERVED
from bugflow.work.domain.models.journal import DispatchedRun
from bugflow.work.domain.services.dispatch_record import DispatchRecordService
from bugflow.work.domain.services.journal import JournalService
from bugflow.work.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries,
)
from bugflow.work.tests.journal import QueryableJournal


class Queries(JournalService, DispatchRecordService, Protocol):
    """Both of the context's reading interfaces."""


#: Given the kinds of fact to search for dispatches, makes somewhere to
#: write entries and somewhere to read them back.
Make = Callable[[Sequence[str]], tuple[RecordingService, Queries]]


@pytest.fixture(params=["memory", "postgres"])
def make(request: pytest.FixtureRequest) -> Make:
    if request.param == "memory":

        def in_memory(
            facts: Sequence[str],
        ) -> tuple[RecordingService, Queries]:
            journal = QueryableJournal(dispatch_facts=facts)
            return journal, journal

        return in_memory
    database_url: str = request.getfixturevalue("database_url")

    def in_postgres(facts: Sequence[str]) -> tuple[RecordingService, Queries]:
        return (
            SqlAlchemyJournal(database_url),
            SqlAlchemyJournalQueries(database_url, dispatch_facts=facts),
        )

    return in_postgres


def unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}"


def entry(
    event_type: str,
    payload: dict[str, Any],
    *,
    repo: str,
    day: int = 1,
    pr_number: int | None = 7,
    run_id: str = "run-1",
) -> JournalEntry:
    return JournalEntry(
        event_id=uuid4(),
        occurred_at=datetime(2030, 5, day, tzinfo=UTC),
        event_type=event_type,
        forge="github",
        repo=repo,
        pr_number=pr_number,
        commit_sha="a" * 40,
        corpus_version="v1",
        workflow_id=f"pr/{repo}/7",
        run_id=run_id,
        agent_id="security",
        payload=payload,
    )


def dispatch(runner: str, remote_id: str, step: str = "dispatched") -> Any:
    return {
        "agent_id": "security",
        "step": step,
        "runner": runner,
        "fingerprint": "f1",
        "remote_id": remote_id,
        "budget": {"usd": 2.0},
    }


def test_a_pull_requests_entries_of_one_type_come_back_oldest_first(
    make: Make,
) -> None:
    recording, queries = make((AGENT_DISPATCHED,))
    name = unique("pear-tree")
    repo = f"orchard/{name}"
    later = entry(PR_OBSERVED, {"n": 2}, repo=repo, day=3)
    earlier = entry(PR_OBSERVED, {"n": 1}, repo=repo, day=2)
    recording.append(
        [
            later,
            earlier,
            entry(AGENT_DISPATCHED, {}, repo=repo),
            entry(PR_OBSERVED, {}, repo=repo, pr_number=8),
            entry(PR_OBSERVED, {}, repo=f"orchard/{unique('other')}"),
        ]
    )

    found = queries.events_for_pull_request(
        PullRequestRef(owner="orchard", repo=name, number=7), PR_OBSERVED
    )

    assert [e.event_id for e in found] == [earlier.event_id, later.event_id]
    assert found[0].payload == {"n": 1}
    assert found[0].commit_sha == "a" * 40


def test_a_runners_work_is_matched_to_the_run_that_dispatched_it(
    make: Make,
) -> None:
    recording, queries = make((AGENT_DISPATCHED,))
    runner, repo = unique("hosted"), f"orchard/{unique('pear-tree')}"
    recording.append(
        [entry(AGENT_DISPATCHED, dispatch(runner, "s-1"), repo=repo)]
    )

    assert queries.dispatched_run(runner, "s-1") == DispatchedRun(
        correlation=Correlation(workflow_id=f"pr/{repo}/7", run_id="run-1"),
        agent_id="security",
        forge="github",
        repo=repo,
        pr_number=7,
        commit_sha="a" * 40,
    )
    assert queries.dispatched_run(runner, "s-2") is None
    assert queries.dispatched_run(unique("local"), "s-1") is None


def test_an_entry_that_started_no_run_is_not_a_match(make: Make) -> None:
    recording, queries = make((AGENT_DISPATCHED,))
    runner, repo = unique("hosted"), f"orchard/{unique('pear-tree')}"
    recording.append(
        [
            entry(
                AGENT_DISPATCHED,
                dispatch(runner, "s-1", step="unavailable"),
                repo=repo,
            )
        ]
    )

    assert queries.dispatched_run(runner, "s-1") is None


def test_a_dispatch_under_another_fact_matches_only_if_it_is_named(
    make: Make,
) -> None:
    recording, named = make((AGENT_DISPATCHED, "survey.dispatched"))
    _, not_named = make((AGENT_DISPATCHED,))
    runner, repo = unique("hosted"), f"orchard/{unique('pear-tree')}"
    written = entry("survey.dispatched", dispatch(runner, "s-1"), repo=repo)
    recording.append([written])

    found = named.dispatched_run(runner, "s-1")

    assert found is not None
    assert found.correlation.workflow_id == written.workflow_id
    if isinstance(recording, SqlAlchemyJournal):
        # The two in-memory journals are separate, so only the database
        # shows that the same entry is not matched when it is not named.
        assert not_named.dispatched_run(runner, "s-1") is None


def test_every_dispatch_that_started_a_run_comes_back_oldest_first(
    make: Make,
) -> None:
    recording, queries = make((AGENT_DISPATCHED, "survey.dispatched"))
    runner, repo = unique("hosted"), f"orchard/{unique('pear-tree')}"
    recording.append(
        [
            entry(AGENT_DISPATCHED, dispatch(runner, "s-2"), repo=repo, day=4),
            entry(AGENT_DISPATCHED, dispatch(runner, "s-1"), repo=repo, day=2),
            entry(AGENT_DISPATCHED, dispatch(runner, ""), repo=repo, day=5),
            entry(
                AGENT_DISPATCHED,
                dispatch(runner, "s-3", step="reused"),
                repo=repo,
            ),
            entry("survey.dispatched", dispatch(runner, "s-4"), repo=repo),
        ]
    )

    mine = [w for w in queries.dispatched_work() if w.repo == repo]

    assert [w.handle.remote_id for w in mine] == ["s-1", "s-2", ""]
    first = mine[0]
    assert first.occurred_at == datetime(2030, 5, 2, tzinfo=UTC)
    assert first.agent_id == "security"
    assert first.corpus_version == "v1"
    assert first.handle.runner == runner
    assert first.handle.budget == Budget(usd=2.0)
