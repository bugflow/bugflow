"""The forge's facts are unpacked as they are written: each has rows of
its own beside the envelope, in the same transaction (ADR 007).

Skipped unless DATABASE_URL names a Postgres server.
"""

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from bugflow.forge.infrastructure.sqlalchemy_forge_facts import (
    UNPACKERS,
    delivery,
    finding_dismissal,
    pull_request_closure,
    pull_request_closure_outstanding,
    pull_request_merge,
    pull_request_observation,
    pull_request_observation_agent,
    pull_request_observation_commit,
    pull_request_observation_component,
    pull_request_observation_delivery,
    pull_request_observation_policy,
    reaction,
    reaction_agent,
    webhook_reconciliation,
    webhook_reconciliation_event,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry, fact_id
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal

AT = datetime(2026, 10, 25, 9, tzinfo=UTC)


def entry(event_type: str, key: str, payload: dict[str, Any]) -> JournalEntry:
    return JournalEntry(
        event_id=fact_id("forge-facts-test", event_type, key),
        occurred_at=AT,
        event_type=event_type,
        forge="github",
        repo="o/r",
        pr_number=7,
        commit_sha=None,
        corpus_version=None,
        workflow_id="review/github/o/r/7",
        run_id="run-1",
        payload=payload,
    )


def one(engine: sa.Engine, table: sa.Table, event_id: object) -> Any:
    with engine.connect() as connection:
        return (
            connection.execute(
                sa.select(table).where(table.c.event_id == event_id)
            )
            .mappings()
            .one()
        )


def rows(
    engine: sa.Engine, table: sa.Table, event_id: object, *order: str
) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        return [
            tuple(r)
            for r in connection.execute(
                sa.select(table)
                .where(table.c.event_id == event_id)
                .order_by(*(table.c[c] for c in order))
            ).all()
        ]


def test_a_delivery_is_unpacked(database_url: str, engine: sa.Engine) -> None:
    received = entry(
        "delivery.received",
        "d-1",
        {
            "delivery_id": "d-1",
            "event": "pull_request",
            "action": None,
            "outcome": "accepted",
            "reason": "known repository",
        },
    )
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append([received])
    row = one(engine, delivery, received.event_id)
    assert (row["event"], row["action"], row["outcome"]) == (
        "pull_request",
        None,
        "accepted",
    )


def test_a_reconciliation_is_unpacked_with_its_events(
    database_url: str, engine: sa.Engine
) -> None:
    reconciled = entry(
        "webhook.reconciled",
        "w-1",
        {
            "url": "https://ingress.example/hook",
            "outcome": "created",
            "detail": "no hook pointed here",
            "events": ["issue_comment", "pull_request"],
        },
    )
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append([reconciled])
    row = one(engine, webhook_reconciliation, reconciled.event_id)
    assert row["outcome"] == "created"
    assert [
        r[1]
        for r in rows(
            engine, webhook_reconciliation_event, reconciled.event_id, "event"
        )
    ] == ["issue_comment", "pull_request"]


def test_an_observation_is_unpacked_with_all_it_carries(
    database_url: str, engine: sa.Engine
) -> None:
    observed = entry(
        "pr.observed",
        "o-1",
        {
            "delivery_id": "d-2",
            "delivery_ids": ["d-1", "d-2"],
            "snapshot_id": "snap-1",
            "corpus": {"doctrine": "v3", "judge": "v9"},
            "installed": {"narrative": "1.2", "security": "0.4"},
            "reviewed_for": ["narrative"],
            "held": ["narrative", "security"],
            "title": "Add a thing",
            "head_branch": "thing",
            "base_branch": "main",
            "author_login": "someone",
            "commits": [
                {
                    "sha": "abc",
                    "author_name": "A",
                    "author_email": "a@x",
                    "author_login": "someone",
                    "committer_name": "GitHub",
                    "committer_email": "noreply@github.com",
                    "committer_login": "web-flow",
                    "verified": True,
                    "verification_reason": "valid",
                }
            ],
            "file_count": 3,
            "changed_lines": 40,
        },
    )
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append([observed])
    row = one(engine, pull_request_observation, observed.event_id)
    assert (row["snapshot_id"], row["author_login"], row["file_count"]) == (
        "snap-1",
        "someone",
        3,
    )
    assert [
        r[2]
        for r in rows(
            engine,
            pull_request_observation_delivery,
            observed.event_id,
            "position",
        )
    ] == ["d-1", "d-2"]
    assert [
        r[1:]
        for r in rows(
            engine,
            pull_request_observation_component,
            observed.event_id,
            "component",
        )
    ] == [("doctrine", "v3"), ("judge", "v9")]
    assert [
        r[1:]
        for r in rows(
            engine, pull_request_observation_agent, observed.event_id, "agent"
        )
    ] == [("narrative", "1.2"), ("security", "0.4")]
    assert [
        r[1:]
        for r in rows(
            engine,
            pull_request_observation_policy,
            observed.event_id,
            "standing",
            "policy_id",
        )
    ] == [
        ("held", "narrative"),
        ("held", "security"),
        ("reviewed_for", "narrative"),
    ]
    (commit,) = rows(
        engine, pull_request_observation_commit, observed.event_id, "position"
    )
    assert commit[2:] == (
        "abc",
        "A",
        "a@x",
        "someone",
        "GitHub",
        "noreply@github.com",
        "web-flow",
        True,
        "valid",
    )


def test_an_observation_with_no_scope_has_no_policy_rows(
    database_url: str, engine: sa.Engine
) -> None:
    observed = entry(
        "pr.observed",
        "o-2",
        {
            "delivery_id": None,
            "delivery_ids": [],
            "snapshot_id": "snap-2",
            "corpus": {"doctrine": "v3", "judge": "v9"},
            "title": "Older",
            "head_branch": "old",
            "base_branch": "main",
            "author_login": "someone",
            "commits": [],
            "file_count": 0,
            "changed_lines": 0,
        },
    )
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append([observed])
    assert (
        one(engine, pull_request_observation, observed.event_id)["delivery_id"]
        is None
    )
    assert (
        rows(engine, pull_request_observation_policy, observed.event_id) == []
    )
    assert (
        rows(engine, pull_request_observation_agent, observed.event_id) == []
    )


def test_a_closure_is_unpacked_with_what_was_outstanding(
    database_url: str, engine: sa.Engine
) -> None:
    closed = entry(
        "pr.closed",
        "c-1",
        {
            "merged": True,
            "outstanding": [
                {"policy_id": "narrative", "clause": "N-3", "subject": "x.md"}
            ],
            "reactions": 2,
        },
    )
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append([closed])
    row = one(engine, pull_request_closure, closed.event_id)
    assert (row["merged"], row["reactions"]) == (True, 2)
    assert [
        r[2:]
        for r in rows(
            engine,
            pull_request_closure_outstanding,
            closed.event_id,
            "position",
        )
    ] == [("narrative", "N-3", "x.md")]


def test_a_merge_is_unpacked(database_url: str, engine: sa.Engine) -> None:
    merged = entry("pr.merged", "m-1", {"delivery_id": "d-3"})
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append([merged])
    assert (
        one(engine, pull_request_merge, merged.event_id)["delivery_id"]
        == "d-3"
    )


def test_a_reaction_is_unpacked_with_its_agents(
    database_url: str, engine: sa.Engine
) -> None:
    reacted = entry(
        "reaction.recorded",
        "r-1",
        {
            "comment_id": 123456789012,
            "agents": ["narrative", "security"],
            "agent_id": None,
            "evaluated_in": "run-0",
            "content": "+1",
            "login": "someone",
            "reacted_at": "2026-10-25T08:00:00+00:00",
        },
    )
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append([reacted])
    row = one(engine, reaction, reacted.event_id)
    assert (row["comment_id"], row["content"], row["agent_id"]) == (
        123456789012,
        "+1",
        None,
    )
    assert row["reacted_at"] == datetime(2026, 10, 25, 8, tzinfo=UTC)
    assert [
        r[2]
        for r in rows(engine, reaction_agent, reacted.event_id, "position")
    ] == ["narrative", "security"]


def test_a_dismissal_is_unpacked(database_url: str, engine: sa.Engine) -> None:
    dismissed = entry(
        "finding.dismissed",
        "f-1",
        {
            "policy_id": "narrative",
            "reason": "the clause does not apply",
            "actor": "someone",
            "comment_id": 42,
            "delivery_id": "d-4",
        },
    )
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append([dismissed])
    row = one(engine, finding_dismissal, dismissed.event_id)
    assert (row["policy_id"], row["actor"], row["comment_id"]) == (
        "narrative",
        "someone",
        42,
    )
