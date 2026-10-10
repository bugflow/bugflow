"""Tests of the review context's questions of the journal.

Each test runs twice: against the in-memory journal the other tests
use, and against the Postgres adapter. The two must give the same
answers. The Postgres half is skipped unless DATABASE_URL names a
Postgres server.

The database is shared by the tests in a session, so each test uses a
repository and a run with names of its own.
"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy.exc import StatementError

from bugflow.review.domain.facts import (
    ACTION_TAKEN,
    FINDING_DISMISSED,
    FINDING_RAISED,
)
from bugflow.review.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries,
)
from bugflow.review.tests.journal import QueryableJournal
from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal

#: Somewhere to write entries, and what reads them back.
Journals = tuple[RecordingService, QueryableJournal | SqlAlchemyJournalQueries]

BUILD = "1" * 40


@pytest.fixture(params=["memory", "postgres"])
def journals(request: pytest.FixtureRequest) -> Journals:
    if request.param == "memory":
        journal = QueryableJournal(build=BUILD)
        return journal, journal
    database_url: str = request.getfixturevalue("database_url")
    return (
        SqlAlchemyJournal(database_url, build=BUILD),
        SqlAlchemyJournalQueries(database_url),
    )


def new_run() -> Correlation:
    return Correlation(workflow_id="test/journal", run_id=str(uuid4()))


def a_repository() -> tuple[str, PullRequestRef]:
    name = f"widgets-{uuid4().hex[:8]}"
    return (
        f"example-org/{name}",
        PullRequestRef(owner="example-org", repo=name, number=1),
    )


def entry(
    run: Correlation,
    key: str,
    event_type: str = FINDING_RAISED,
    repo: str = "example-org/widgets",
    number: int | None = 1,
    day: int | None = None,
) -> JournalEntry:
    return JournalEntry(
        event_id=event_id(run, event_type, key),
        occurred_at=(
            datetime(2030, 5, day, tzinfo=UTC) if day else datetime.now(UTC)
        ),
        event_type=event_type,
        forge="github",
        repo=repo,
        pr_number=number,
        commit_sha=None,
        corpus_version="v1",
        workflow_id=run.workflow_id,
        run_id=run.run_id,
        payload={"key": key},
    )


def test_a_runs_entries_are_read_back(journals: Journals) -> None:
    recording, queries = journals
    run = new_run()
    recording.append([entry(run, "a"), entry(run, "b")])
    recording.append([entry(new_run(), "c")])

    read = queries.entries_for_run(run)

    assert {e.payload["key"] for e in read} == {"a", "b"}


def test_a_repeated_event_id_is_read_back_once(journals: Journals) -> None:
    recording, queries = journals
    run = new_run()
    recording.append([entry(run, "a")])
    recording.append([entry(run, "a")])
    assert len(queries.entries_for_run(run)) == 1


def test_the_build_that_wrote_an_entry_comes_back_with_it(
    journals: Journals,
) -> None:
    recording, queries = journals
    run = new_run()
    recording.append([replace(entry(run, "a"), build="0" * 40)])
    assert [e.build for e in queries.entries_for_run(run)] == [BUILD]


def test_a_payload_json_cannot_hold_is_refused_and_records_nothing(
    journals: Journals,
) -> None:
    recording, queries = journals
    run = new_run()
    unsayable = replace(entry(run, "a"), payload={"at": datetime.now(UTC)})
    with pytest.raises((TypeError, StatementError)):
        recording.append([entry(run, "b"), unsayable])
    assert queries.entries_for_run(run) == []


def test_the_latest_run_that_acted_is_found_excluding_one_run(
    journals: Journals,
) -> None:
    recording, queries = journals
    repo, ref = a_repository()
    first, second, current = new_run(), new_run(), new_run()
    assert queries.latest_acted_run(ref, excluding=current) is None

    recording.append([entry(first, "c", ACTION_TAKEN, repo)])
    recording.append([entry(second, "c", ACTION_TAKEN, repo)])
    recording.append([entry(second, "f", FINDING_RAISED, "example-org/other")])
    recording.append([entry(current, "c", ACTION_TAKEN, repo)])

    assert queries.latest_acted_run(ref, excluding=current) == second
    assert queries.latest_acted_run(ref, excluding=second) == current


def test_a_pull_requests_entries_of_one_type_come_back_oldest_first(
    journals: Journals,
) -> None:
    recording, queries = journals
    repo, ref = a_repository()
    run = new_run()
    recording.append(
        [
            entry(run, "12", FINDING_DISMISSED, repo, day=12),
            entry(run, "10", FINDING_RAISED, repo, day=10),
            entry(run, "9", FINDING_DISMISSED, repo, number=7, day=9),
            entry(run, "11", FINDING_DISMISSED, repo, day=11),
        ]
    )

    found = queries.events_for_pull_request(ref, FINDING_DISMISSED)

    assert [e.payload["key"] for e in found] == ["11", "12"]


def test_a_repositorys_entries_of_one_type_come_back_oldest_first(
    journals: Journals,
) -> None:
    """Whether or not an entry belongs to a pull request: a stocktake's
    entries belong to none."""
    recording, queries = journals
    repo, _ = a_repository()
    other, _ = a_repository()
    run = new_run()
    recording.append(
        [
            entry(run, "3", ACTION_TAKEN, repo, number=None, day=3),
            entry(run, "2", ACTION_TAKEN, repo, number=4, day=2),
            entry(run, "1", FINDING_RAISED, repo, day=1),
            entry(run, "4", ACTION_TAKEN, other, day=4),
        ]
    )

    found = queries.events_for_repository("github", repo, ACTION_TAKEN)

    assert [e.payload["key"] for e in found] == ["2", "3"]
