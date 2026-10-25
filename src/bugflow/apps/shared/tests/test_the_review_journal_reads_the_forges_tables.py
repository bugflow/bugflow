"""The review context's two questions of the forge's facts, the
observations and the dismissals of a pull request, answered alike by the
in-memory journal the review's tests use and by the Postgres adapter
over the forge's tables (ADR 007).

The Postgres half writes each fact through the unpackers every program
composes, so the typed row the adapter reads is the one a program would
have written. It is skipped unless DATABASE_URL names a Postgres server.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from bugflow.apps.shared.journals import UNPACKERS
from bugflow.forge.tests.payloads import dismissed, observed
from bugflow.review.domain.facts import FINDING_DISMISSED, PR_OBSERVED
from bugflow.review.domain.models.observation import Observation
from bugflow.review.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries,
)
from bugflow.review.tests.journal import QueryableJournal
from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.dismissal import Dismissal
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal

#: Somewhere to write facts, and what reads them back.
Journals = tuple[RecordingService, QueryableJournal | SqlAlchemyJournalQueries]

BUILD = "2" * 40


@pytest.fixture(params=["memory", "postgres"])
def journals(request: pytest.FixtureRequest) -> Journals:
    if request.param == "memory":
        journal = QueryableJournal(build=BUILD)
        return journal, journal
    database_url: str = request.getfixturevalue("database_url")
    return (
        SqlAlchemyJournal(database_url, build=BUILD, unpackers=UNPACKERS),
        SqlAlchemyJournalQueries(database_url),
    )


def a_repository() -> tuple[str, PullRequestRef]:
    name = f"widgets-{uuid4().hex[:8]}"
    return (
        f"example-org/{name}",
        PullRequestRef(owner="example-org", repo=name, number=1),
    )


def new_run() -> Correlation:
    return Correlation(workflow_id="test/forge-facts", run_id=str(uuid4()))


def fact(
    run: Correlation,
    event_type: str,
    repo: str,
    payload: dict[str, Any],
    *,
    number: int = 1,
    day: int = 1,
    commit_sha: str | None = "c" * 40,
    corpus_version: str | None = "v1",
    origin: str | None = None,
) -> JournalEntry:
    return JournalEntry(
        event_id=event_id(run, event_type, str(day)),
        occurred_at=datetime(2030, 5, day, tzinfo=UTC),
        event_type=event_type,
        forge="github",
        repo=repo,
        pr_number=number,
        commit_sha=commit_sha,
        corpus_version=corpus_version,
        workflow_id=run.workflow_id,
        run_id=run.run_id,
        payload=payload,
        origin=origin,
    )


def test_the_observations_of_a_pull_request_come_oldest_first(
    journals: Journals,
) -> None:
    recording, queries = journals
    repo, ref = a_repository()
    first, second = new_run(), new_run()
    recording.append(
        [
            fact(second, PR_OBSERVED, repo, observed("b" * 64), day=2),
            fact(first, PR_OBSERVED, repo, observed("a" * 64), day=1),
            fact(new_run(), PR_OBSERVED, repo, observed("c" * 64), number=2),
        ]
    )

    found = queries.observations_for_pull_request(ref)

    assert found == [
        Observation(
            correlation=first,
            commit_sha="c" * 40,
            corpus_version="v1",
            snapshot_id="a" * 64,
        ),
        Observation(
            correlation=second,
            commit_sha="c" * 40,
            corpus_version="v1",
            snapshot_id="b" * 64,
        ),
    ]


def test_the_dismissals_on_a_pull_request_come_oldest_first(
    journals: Journals,
) -> None:
    recording, queries = journals
    repo, ref = a_repository()
    run = new_run()
    recording.append(
        [
            fact(run, FINDING_DISMISSED, repo, dismissed("B", "later"), day=2),
            fact(run, FINDING_DISMISSED, repo, dismissed("A", "first"), day=1),
            fact(
                run, FINDING_DISMISSED, repo, dismissed("C", "other"), number=2
            ),
        ]
    )

    found = queries.dismissals_for_pull_request(ref)

    assert found == [
        Dismissal(policy_id="A", reason="first", actor="reviewer"),
        Dismissal(policy_id="B", reason="later", actor="reviewer"),
    ]


def test_an_origin_keeps_the_facts_of_another_origin_out(
    journals: Journals,
) -> None:
    """Two repositories of one name at two origins share a journal
    scope by name; a read for one origin sees only its own facts."""
    recording, queries = journals
    repo, ref = a_repository()
    here, there = new_run(), new_run()
    recording.append(
        [
            fact(
                here,
                PR_OBSERVED,
                repo,
                observed("a" * 64),
                day=1,
                origin=f"github.com/{repo}",
            ),
            fact(
                there,
                PR_OBSERVED,
                repo,
                observed("b" * 64),
                day=2,
                origin=f"forge.example/{repo}",
            ),
            fact(
                here,
                FINDING_DISMISSED,
                repo,
                dismissed("A", "here"),
                day=3,
                origin=f"github.com/{repo}",
            ),
            fact(
                there,
                FINDING_DISMISSED,
                repo,
                dismissed("B", "there"),
                day=4,
                origin=f"forge.example/{repo}",
            ),
        ]
    )

    seen = queries.observations_for_pull_request(
        ref, origin=f"github.com/{repo}"
    )
    assert [o.snapshot_id for o in seen] == ["a" * 64]
    assert [
        d.policy_id
        for d in queries.dismissals_for_pull_request(
            ref, origin=f"github.com/{repo}"
        )
    ] == ["A"]
    assert len(queries.observations_for_pull_request(ref)) == 2
