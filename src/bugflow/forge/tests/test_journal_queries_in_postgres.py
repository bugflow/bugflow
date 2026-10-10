"""Tests of the forge's journal queries, against a real database.

Skipped unless DATABASE_URL names a Postgres server.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import sqlalchemy as sa

from bugflow.forge.domain import facts
from bugflow.forge.infrastructure.sqlalchemy_journal_queries import (
    SqlAlchemyJournalQueries,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal

AT = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


def entry(
    event_type: str, ref: PullRequestRef, occurred_at: datetime = AT
) -> JournalEntry:
    return JournalEntry(
        event_id=uuid4(),
        occurred_at=occurred_at,
        event_type=event_type,
        forge=ref.forge,
        repo=f"{ref.owner}/{ref.repo}",
        pr_number=ref.number,
        commit_sha=None,
        corpus_version=None,
        workflow_id="delivery/github",
        run_id=uuid4().hex,
        payload={},
    )


def unique_ref(
    forge: Literal["github", "forgejo"] = "github",
) -> PullRequestRef:
    return PullRequestRef(
        forge=forge, owner="o", repo=f"r-{uuid4().hex[:8]}", number=1
    )


def test_a_delivery_received_since_a_time_is_found(
    engine: sa.Engine, database_url: str
) -> None:
    ref = unique_ref()
    SqlAlchemyJournal(database_url).append(
        [entry(facts.DELIVERY_RECEIVED, ref)]
    )
    queries = SqlAlchemyJournalQueries(database_url)
    assert queries.received_since(ref, AT - timedelta(minutes=1))
    assert queries.received_since(ref, AT)
    assert not queries.received_since(ref, AT + timedelta(minutes=1))


def test_another_pull_requests_delivery_does_not_count(
    engine: sa.Engine, database_url: str
) -> None:
    ref = unique_ref()
    other = PullRequestRef(owner=ref.owner, repo=ref.repo, number=2)
    SqlAlchemyJournal(database_url).append(
        [
            entry(facts.DELIVERY_RECEIVED, other),
            entry(facts.PR_OBSERVED, ref),
        ]
    )
    assert not SqlAlchemyJournalQueries(database_url).received_since(
        ref, AT - timedelta(minutes=1)
    )


def test_the_repositories_with_a_fact_are_listed_once_each(
    engine: sa.Engine, database_url: str
) -> None:
    ref = unique_ref()
    fact = f"test.{uuid4().hex[:8]}"
    SqlAlchemyJournal(database_url).append(
        [
            entry(fact, ref),
            entry(fact, ref),
            entry(fact, unique_ref("forgejo")),
        ]
    )
    listed = SqlAlchemyJournalQueries(database_url).repositories_with(fact)
    assert len(listed) == 2
    assert ("github", f"{ref.owner}/{ref.repo}") in listed
    assert listed == sorted(listed)


def test_a_pull_requests_events_come_back_in_order(
    engine: sa.Engine, database_url: str
) -> None:
    ref = unique_ref()
    later = entry(facts.PR_OBSERVED, ref, AT + timedelta(hours=1))
    earlier = entry(facts.PR_OBSERVED, ref)
    SqlAlchemyJournal(database_url).append([later, earlier])
    found = SqlAlchemyJournalQueries(database_url).events_for_pull_request(
        ref, facts.PR_OBSERVED
    )
    assert [e.event_id for e in found] == [earlier.event_id, later.event_id]
