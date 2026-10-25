"""A deploy is unpacked as it is written: a row of its own beside the
envelope, in the same transaction (ADR 007).

Skipped unless DATABASE_URL names a Postgres server.
"""

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from bugflow.method.infrastructure.sqlalchemy_method_facts import (
    UNPACKERS,
    policy_deploy,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry, fact_id
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal

AT = datetime(2026, 10, 25, 10, tzinfo=UTC)


def entry(key: str, payload: dict[str, Any]) -> JournalEntry:
    return JournalEntry(
        event_id=fact_id("method-facts-test", key),
        occurred_at=AT,
        event_type="policies.deployed",
        forge="",
        repo="",
        pr_number=None,
        commit_sha=None,
        corpus_version=None,
        workflow_id="deploy-policies",
        run_id="o/policies@abc",
        payload=payload,
    )


def one(engine: sa.Engine, event_id: object) -> Any:
    with engine.connect() as connection:
        return (
            connection.execute(
                sa.select(policy_deploy).where(
                    policy_deploy.c.event_id == event_id
                )
            )
            .mappings()
            .one()
        )


def test_a_deploy_is_unpacked_with_the_deployment_it_replaced(
    database_url: str, engine: sa.Engine
) -> None:
    first = entry(
        "first",
        {
            "repository": "o/policies",
            "commit": "abc",
            "content_hash": "h1",
            "files": 12,
            "sent_by": "deployer",
            "replaced": None,
        },
    )
    second = entry(
        "second",
        {
            "repository": "o/policies",
            "commit": "def",
            "content_hash": "h2",
            "files": 13,
            "sent_by": "deployer",
            "replaced": {
                "repository": "o/policies",
                "commit": "abc",
                "content_hash": "h1",
            },
        },
    )
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append(
        [first, second]
    )
    opening = one(engine, first.event_id)
    assert (opening["commit"], opening["files"], opening["sent_by"]) == (
        "abc",
        12,
        "deployer",
    )
    assert opening["replaced_commit"] is None
    following = one(engine, second.event_id)
    assert (
        following["replaced_repository"],
        following["replaced_commit"],
        following["replaced_content_hash"],
    ) == ("o/policies", "abc", "h1")
