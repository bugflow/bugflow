"""The archive's facts are unpacked as they are written: a seal, a
registration and a refusal each have a row of their own beside the
envelope, in the same transaction (ADR 007).

Skipped unless DATABASE_URL names a Postgres server.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa

from bugflow.archive.domain import facts
from bugflow.archive.infrastructure.sqlalchemy_archive_facts import (
    UNPACKERS,
    archive_refusal,
    archive_registration,
    archive_registration_beside,
    archive_seal,
    archive_seal_claim,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal

AT = datetime(2026, 10, 24, 12, tzinfo=UTC)


def entry(
    event_type: str, event_id: UUID, payload: dict[str, Any]
) -> JournalEntry:
    return JournalEntry(
        event_id=event_id,
        occurred_at=AT,
        event_type=event_type,
        forge="github",
        repo="o/r",
        pr_number=None,
        commit_sha=None,
        corpus_version=None,
        workflow_id="archive/kept",
        run_id="run-1",
        payload=payload,
    )


def test_a_seal_is_unpacked_with_its_claims(
    database_url: str, engine: sa.Engine
) -> None:
    sealed = entry(
        facts.SEALED,
        facts.sealed_id("ledger-1", "0001-first"),
        {
            "ledger_id": "ledger-1",
            "scope": "notes",
            "name": "0001-first",
            "head": "bafyhead",
            "root": None,
            "events": 1,
            "files": 2,
            "bytes": 345,
            "caller": "subject-1",
            "client": "coding-agent",
            "claims": {"branch": "master", "remote.origin": "git@x:o/r.git"},
        },
    )
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append([sealed])
    if True:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(archive_seal).where(
                        archive_seal.c.event_id == sealed.event_id
                    )
                )
                .mappings()
                .one()
            )
            claims = connection.execute(
                sa.select(
                    archive_seal_claim.c.claim, archive_seal_claim.c.value
                )
                .where(archive_seal_claim.c.event_id == sealed.event_id)
                .order_by(archive_seal_claim.c.claim)
            ).all()
    assert (row["ledger_id"], row["files"], row["bytes"], row["root"]) == (
        "ledger-1",
        2,
        345,
        None,
    )
    assert [tuple(c) for c in claims] == [
        ("branch", "master"),
        ("remote.origin", "git@x:o/r.git"),
    ]


def test_a_registration_is_unpacked_with_what_is_beside_it(
    database_url: str, engine: sa.Engine
) -> None:
    bound = entry(
        facts.BOUND,
        facts.bound_id("ledger-2", "github", "o/r", "notes", AT),
        {
            "ledger_id": "ledger-2",
            "scope": "notes",
            "replaces": {
                "forge": "github",
                "repo": "o/old",
                "scope": "notes",
                "origin": None,
            },
            "beside": ["ledger-3", "ledger-4"],
        },
    )
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append([bound])
    if True:
        with engine.connect() as connection:
            row = (
                connection.execute(
                    sa.select(archive_registration).where(
                        archive_registration.c.event_id == bound.event_id
                    )
                )
                .mappings()
                .one()
            )
            beside = (
                connection.execute(
                    sa.select(archive_registration_beside.c.ledger_id)
                    .where(
                        archive_registration_beside.c.event_id
                        == bound.event_id
                    )
                    .order_by(archive_registration_beside.c.position)
                )
                .scalars()
                .all()
            )
    assert (row["replaces_repo"], row["replaces_origin"]) == ("o/old", None)
    assert beside == ["ledger-3", "ledger-4"]


def test_a_refusal_is_unpacked(database_url: str, engine: sa.Engine) -> None:
    refused = entry(
        facts.REFUSED,
        facts.refused_id("ledger-5", "0002-second", "not-next", AT),
        {
            "ledger_id": "ledger-5",
            "scope": "notes",
            "name": "0002-second",
            "kind": "not-next",
            "caller": "subject-1",
            "client": "coding-agent",
        },
    )
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append([refused])
    if True:
        with engine.connect() as connection:
            kind = connection.execute(
                sa.select(archive_refusal.c.kind).where(
                    archive_refusal.c.event_id == refused.event_id
                )
            ).scalar_one()
    assert kind == "not-next"
