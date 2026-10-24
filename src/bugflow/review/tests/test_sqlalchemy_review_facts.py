"""The review's facts are unpacked as they are written: each has rows of
its own beside the envelope, in the same transaction (ADR 007).

Skipped unless DATABASE_URL names a Postgres server.
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

from bugflow.review.infrastructure.sqlalchemy_review_facts import (
    UNPACKERS,
    agent_dispatch,
    agent_dispatch_withheld_file,
    judge_invocation,
    judge_invocation_unsupported,
    model_call,
    model_call_finish_reason,
    model_call_object,
    policy_check,
    raised_finding,
    resolved_finding,
    review_action,
    review_action_removed_label,
    review_grade,
    withheld_finding,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry, fact_id
from bugflow.shared.infrastructure.sqlalchemy_journal import SqlAlchemyJournal

AT = datetime(2026, 10, 25, 10, tzinfo=UTC)

JUDGE = {
    "model": "judge-model",
    "fingerprint": "fp",
    "prompt_hash": "ph",
    "input_hash": "ih",
    "exchange_id": "ex-1",
}

FINDING = {
    "policy_id": "narrative",
    "severity": "warn",
    "clause": "N-3",
    "subject": "x.md",
    "message": "Says too much",
    "judged_by": "judge-1",
    "judge": JUDGE,
    "corpus_version": "v3",
    "agent_id": "narrative",
}


def entry(event_type: str, key: str, payload: dict[str, Any]) -> JournalEntry:
    return JournalEntry(
        event_id=fact_id("review-facts-test", event_type, key),
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


def write(database_url: str, *entries: JournalEntry) -> None:
    SqlAlchemyJournal(database_url, unpackers=UNPACKERS).append(list(entries))


def test_a_review_comment_is_an_action_with_its_counts(
    database_url: str, engine: sa.Engine
) -> None:
    commented = entry(
        "action.taken",
        "comment",
        {
            "action": "review_comment",
            "agent_id": "narrative",
            "performed": True,
            "status": "published",
            "comment_id": 41,
            "verdict": "warn",
            "head_sha": "abc",
            "finding_count": 2,
            "raised_count": 1,
            "fixed_count": 0,
            "dismissed_count": 1,
        },
    )
    write(database_url, commented)
    row = one(engine, review_action, commented.event_id)
    assert (row["action"], row["comment_id"], row["verdict"]) == (
        "review_comment",
        41,
        "warn",
    )
    assert (row["raised_count"], row["label"], row["context"]) == (
        1,
        None,
        None,
    )


def test_a_label_is_an_action_with_the_labels_removed(
    database_url: str, engine: sa.Engine
) -> None:
    labelled = entry(
        "action.taken",
        "label",
        {
            "action": "outcome_label",
            "performed": True,
            "status": "published",
            "label": "review: warn",
            "removed": ["review: fail", "review: pass"],
        },
    )
    write(database_url, labelled)
    assert one(engine, review_action, labelled.event_id)["label"] == (
        "review: warn"
    )
    assert [
        r[1]
        for r in rows(
            engine, review_action_removed_label, labelled.event_id, "label"
        )
    ] == ["review: fail", "review: pass"]


def test_a_dispatch_is_unpacked_with_its_budget_and_withheld_files(
    database_url: str, engine: sa.Engine
) -> None:
    dispatched = entry(
        "agent.dispatched",
        "dispatched",
        {
            "agent_id": "narrative",
            "step": "dispatched",
            "runner": "codex",
            "fingerprint": "fp",
            "remote_id": "r-1",
            "budget": {"usd": 5.0, "turns": None},
            "withheld": ["secrets.env", "key.pem"],
        },
    )
    collected = entry(
        "agent.dispatched",
        "collected",
        {
            "agent_id": "narrative",
            "step": "collected",
            "outcome": "answered",
            "runner": "codex",
            "fingerprint": "fp",
            "cost": {"usd": 0.42, "seconds": 61.5},
            "events": 12,
            "detail": "",
            "write_up_id": "w-1",
        },
    )
    write(database_url, dispatched, collected)
    first = one(engine, agent_dispatch, dispatched.event_id)
    assert (first["budget_usd"], first["budget_turns"], first["cost_usd"]) == (
        5.0,
        None,
        None,
    )
    assert [
        r[2]
        for r in rows(
            engine,
            agent_dispatch_withheld_file,
            dispatched.event_id,
            "position",
        )
    ] == ["secrets.env", "key.pem"]
    second = one(engine, agent_dispatch, collected.event_id)
    assert (
        second["cost_seconds"],
        second["events"],
        second["write_up_id"],
    ) == (
        61.5,
        12,
        "w-1",
    )


def test_a_finding_carries_its_judge_and_a_resolution_what_raised_it(
    database_url: str, engine: sa.Engine
) -> None:
    raised = entry("finding.raised", "raised", dict(FINDING))
    unjudged = entry(
        "finding.raised",
        "checked",
        {**FINDING, "judged_by": None, "judge": None},
    )
    resolved = entry(
        "finding.resolved",
        "resolved",
        {
            **FINDING,
            "raised_in_workflow_id": "review/github/o/r/7",
            "raised_in_run_id": "run-0",
        },
    )
    withheld = entry(
        "finding.withheld", "withheld", {**FINDING, "share": 0.25}
    )
    write(database_url, raised, unjudged, resolved, withheld)
    judged = one(engine, raised_finding, raised.event_id)
    assert (judged["judge_model"], judged["judge_exchange_id"]) == (
        "judge-model",
        "ex-1",
    )
    assert (
        one(engine, raised_finding, unjudged.event_id)["judge_model"] is None
    )
    assert (
        one(engine, resolved_finding, resolved.event_id)["raised_in_run_id"]
        == "run-0"
    )
    assert one(engine, withheld_finding, withheld.event_id)["share"] == 0.25


def test_an_invocation_is_unpacked_with_the_verdicts_dropped(
    database_url: str, engine: sa.Engine
) -> None:
    invoked = entry(
        "judge.invoked",
        "invoked",
        {
            "policy_id": "narrative",
            "status": "judged",
            "model": "judge-model",
            "finding_count": 2,
            "unsupported": ["quoted words not there"],
            "input_tokens": 1200,
            "output_tokens": 300,
            "identity": JUDGE,
        },
    )
    write(database_url, invoked)
    row = one(engine, judge_invocation, invoked.event_id)
    assert (row["finding_count"], row["identity_fingerprint"]) == (2, "fp")
    assert [
        r[2]
        for r in rows(
            engine, judge_invocation_unsupported, invoked.event_id, "position"
        )
    ] == ["quoted words not there"]


def test_a_call_is_unpacked_with_exact_costs_and_its_objects(
    database_url: str, engine: sa.Engine
) -> None:
    called = entry(
        "llm.called",
        "call",
        {
            "call_id": "c-1",
            "archive_folder": "calls/2026/10",
            "purpose": "judge",
            "policy_id": "narrative",
            "status": "ok",
            "http_status": 200,
            "error": None,
            "requested_model": "judge-model",
            "answered_model": "judge-model-2",
            "model_id": "m-2",
            "model_group": "judges",
            "api_base": None,
            "proxy_version": "1.2.3",
            "attempt": 1,
            "retries": 0,
            "fallbacks": 1,
            "finish_reasons": ["stop"],
            "input_tokens": 1200,
            "output_tokens": 300,
            "cached_input_tokens": 100,
            "cache_creation_input_tokens": 0,
            "reasoning_output_tokens": None,
            "total_tokens": 1500,
            "cost_usd": "0.0123456789",
            "cost_nanodollars": 12345679,
            "cost_input_usd": "0.01",
            "cost_output_usd": "0.0023456789",
            "cost_cache_read_usd": None,
            "cost_cache_creation_usd": None,
            "cost_reasoning_usd": None,
            "started_at": "2026-10-25T09:00:00+00:00",
            "ended_at": "2026-10-25T09:00:02.500000+00:00",
            "client_duration_ms": 2500.0,
            "provider_duration_ms": 2400.0,
            "proxy_overhead_ms": 100.0,
            "trace_id": "t-1",
            "span_id": "s-1",
            "objects": [
                {
                    "hop": "request",
                    "key": "calls/c-1/request.json.gz",
                    "sha256": "abc",
                    "bytes": 2048,
                    "encoding": "gzip",
                }
            ],
        },
    )
    write(database_url, called)
    row = one(engine, model_call, called.event_id)
    assert row["cost_usd"] == Decimal("0.0123456789")
    assert row["ended_at"] == datetime(
        2026, 10, 25, 9, 0, 2, 500000, tzinfo=UTC
    )
    assert (row["fallbacks"], row["api_base"], row["cost_cache_read_usd"]) == (
        1,
        None,
        None,
    )
    assert [
        r[2]
        for r in rows(
            engine, model_call_finish_reason, called.event_id, "position"
        )
    ] == ["stop"]
    (stored,) = rows(engine, model_call_object, called.event_id, "position")
    assert stored[2:] == (
        "request",
        "calls/c-1/request.json.gz",
        "abc",
        2048,
        "gzip",
    )


def test_a_check_and_a_grade_are_unpacked(
    database_url: str, engine: sa.Engine
) -> None:
    checked = entry(
        "policy.checked",
        "checked",
        {
            "policy_id": "secrets",
            "clause": "S-1",
            "finding_count": 0,
            "cost": {"usd": 0.001},
        },
    )
    graded = entry(
        "review.graded",
        "graded",
        {"agent_id": "narrative", "status": None, "detail": "no verdict"},
    )
    write(database_url, checked, graded)
    assert one(engine, policy_check, checked.event_id)["cost_usd"] == 0.001
    grade = one(engine, review_grade, graded.event_id)
    assert (grade["status"], grade["detail"]) == (None, "no verdict")
