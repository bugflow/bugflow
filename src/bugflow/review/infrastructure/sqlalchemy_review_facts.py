"""The review's ten facts, unpacked into tables named for what one row
is (ADR 007).

An ``action.taken`` row is an action on the pull request: a review
comment, a commit status, an outcome label or, before 19 September
2026, a summary comment. The ``action`` column says which, and the
columns the other actions do not carry are null: a comment has its id,
verdict, head commit and counts, a status its context, state and
description, a label its name and the labels removed, each a row.

An ``agent.dispatched`` row is a step of a checkout agent's dispatch,
named by ``step``: ``dispatched`` with the runner's handle, the budget
and the files withheld, each a row; ``collected`` with the outcome, the
cost and the write-up; ``recovered`` with the write-up found later; and
``refused``, ``reused``, ``no-worktree`` and ``unavailable`` for the
ways no run started.

A ``finding.raised`` row is a raised finding, a ``finding.resolved``
row a resolved one, a ``finding.rewritten`` row one whose quoted words
are gone, and a ``finding.withheld`` row a warning kept out of the pull
request. Each carries the finding and the judge identity it came from,
where a judge did; a resolution and a rewrite name the run that raised
the finding, and a withholding the share being kept out.

A ``judge.invoked`` row is a judge invocation, with the verdicts the
judge gave that were dropped as rows. An ``llm.called`` row is one call
to a language model, with the finish reasons and the stored objects as
rows. A ``policy.checked`` row is a checked policy's run, and a
``review.graded`` row a grade.

Each table is keyed by the event's id, a foreign key to the review
journal. ``UNPACKERS`` writes the typed rows from the envelope's payload
in the envelope's transaction; the script that made the tables filled
them from the rows already there.
"""

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.schema import SchemaItem

from bugflow.shared.domain.models.journal_entry import JournalEntry

metadata = sa.MetaData()


def _event_id(references: str = "review_journal") -> sa.Column[Any]:
    return sa.Column(
        "event_id",
        PG_UUID(as_uuid=True),
        sa.ForeignKey(f"{references}.event_id"),
        primary_key=True,
    )


review_action = sa.Table(
    "review_action",
    metadata,
    _event_id(),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("performed", sa.Boolean, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    # The reviewer that spoke, for a comment or a status.
    sa.Column("agent_id", sa.Text),
    # A review comment or a summary comment.
    sa.Column("comment_id", sa.BigInteger),
    sa.Column("verdict", sa.Text),
    sa.Column("head_sha", sa.Text),
    sa.Column("finding_count", sa.Integer),
    sa.Column("raised_count", sa.Integer),
    sa.Column("fixed_count", sa.Integer),
    sa.Column("dismissed_count", sa.Integer),
    # A commit status.
    sa.Column("context", sa.Text),
    sa.Column("state", sa.Text),
    sa.Column("description", sa.Text),
    # An outcome label.
    sa.Column("label", sa.Text),
    sa.Index("review_action_action_idx", "action"),
)

review_action_removed_label = sa.Table(
    "review_action_removed_label",
    metadata,
    _event_id("review_action"),
    sa.Column("label", sa.Text, primary_key=True),
)

agent_dispatch = sa.Table(
    "agent_dispatch",
    metadata,
    _event_id(),
    sa.Column("agent_id", sa.Text, nullable=False),
    sa.Column("step", sa.Text, nullable=False),
    sa.Column("runner", sa.Text),
    sa.Column("fingerprint", sa.Text),
    sa.Column("remote_id", sa.Text),
    # The limit the run was given, in dollars and turns; null for no
    # limit, or for a step that records none.
    sa.Column("budget_usd", sa.Float),
    sa.Column("budget_turns", sa.Float),
    # What the run cost, recorded when it was collected.
    sa.Column("cost_usd", sa.Float),
    sa.Column("cost_seconds", sa.Float),
    sa.Column("events", sa.Integer),
    sa.Column("detail", sa.Text),
    sa.Column("outcome", sa.Text),
    sa.Column("write_up_id", sa.Text),
    sa.Column("dispatched_at", sa.DateTime(timezone=True)),
    # Why no run started, for the steps that say so.
    sa.Column("reason", sa.Text),
    # The run whose verdict was reused.
    sa.Column("reviewed_in", sa.Text),
    sa.Index("agent_dispatch_step_idx", "step"),
)

agent_dispatch_withheld_file = sa.Table(
    "agent_dispatch_withheld_file",
    metadata,
    _event_id("agent_dispatch"),
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("path", sa.Text, nullable=False),
)


def _finding_columns() -> list[SchemaItem]:
    """The columns of a finding and of the judge identity it came from,
    the identity's five null where no judge did."""
    return [
        sa.Column("policy_id", sa.Text, nullable=False),
        sa.Column("severity", sa.Text, nullable=False),
        sa.Column("clause", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("judged_by", sa.Text),
        sa.Column("judge_model", sa.Text),
        sa.Column("judge_fingerprint", sa.Text),
        sa.Column("judge_prompt_hash", sa.Text),
        sa.Column("judge_input_hash", sa.Text),
        sa.Column("judge_exchange_id", sa.Text),
        sa.Column("corpus_version", sa.Text),
        sa.Column("agent_id", sa.Text),
    ]


def _raised_in() -> list[SchemaItem]:
    return [
        sa.Column("raised_in_workflow_id", sa.Text, nullable=False),
        sa.Column("raised_in_run_id", sa.Text, nullable=False),
    ]


raised_finding = sa.Table(
    "raised_finding",
    metadata,
    _event_id(),
    *_finding_columns(),
    sa.Index("raised_finding_policy_idx", "policy_id"),
)

resolved_finding = sa.Table(
    "resolved_finding",
    metadata,
    _event_id(),
    *_finding_columns(),
    *_raised_in(),
)

rewritten_finding = sa.Table(
    "rewritten_finding",
    metadata,
    _event_id(),
    *_finding_columns(),
    *_raised_in(),
)

withheld_finding = sa.Table(
    "withheld_finding",
    metadata,
    _event_id(),
    *_finding_columns(),
    # The share of warnings being kept out when this one was.
    sa.Column("share", sa.Float, nullable=False),
)

judge_invocation = sa.Table(
    "judge_invocation",
    metadata,
    _event_id(),
    sa.Column("policy_id", sa.Text),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("model", sa.Text),
    sa.Column("finding_count", sa.Integer, nullable=False),
    sa.Column("input_tokens", sa.Integer, nullable=False),
    sa.Column("output_tokens", sa.Integer, nullable=False),
    # The identity of the judgement, enough to run it again; null
    # where the judge recorded none.
    sa.Column("identity_model", sa.Text),
    sa.Column("identity_fingerprint", sa.Text),
    sa.Column("identity_prompt_hash", sa.Text),
    sa.Column("identity_input_hash", sa.Text),
    sa.Column("identity_exchange_id", sa.Text),
    sa.Index("judge_invocation_policy_idx", "policy_id"),
)

#: A verdict the judge gave that was dropped because the words it quoted
#: are not in the submission.
judge_invocation_unsupported = sa.Table(
    "judge_invocation_unsupported",
    metadata,
    _event_id("judge_invocation"),
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("verdict", sa.Text, nullable=False),
)

model_call = sa.Table(
    "model_call",
    metadata,
    _event_id(),
    sa.Column("call_id", sa.Text, nullable=False),
    # Where the call's objects are kept; null for a call recorded
    # before the folder was.
    sa.Column("archive_folder", sa.Text),
    sa.Column("purpose", sa.Text, nullable=False),
    sa.Column("policy_id", sa.Text),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("http_status", sa.Integer),
    sa.Column("error", sa.Text),
    sa.Column("requested_model", sa.Text, nullable=False),
    sa.Column("answered_model", sa.Text),
    sa.Column("model_id", sa.Text),
    sa.Column("model_group", sa.Text),
    sa.Column("api_base", sa.Text),
    sa.Column("proxy_version", sa.Text),
    sa.Column("attempt", sa.Integer, nullable=False),
    sa.Column("retries", sa.Integer),
    sa.Column("fallbacks", sa.Integer),
    sa.Column("input_tokens", sa.Integer),
    sa.Column("output_tokens", sa.Integer),
    sa.Column("cached_input_tokens", sa.Integer),
    sa.Column("cache_creation_input_tokens", sa.Integer),
    sa.Column("reasoning_output_tokens", sa.Integer),
    sa.Column("total_tokens", sa.Integer),
    # The costs in dollars, exact as the proxy gave them.
    sa.Column("cost_usd", sa.Numeric),
    sa.Column("cost_nanodollars", sa.BigInteger),
    sa.Column("cost_input_usd", sa.Numeric),
    sa.Column("cost_output_usd", sa.Numeric),
    sa.Column("cost_cache_read_usd", sa.Numeric),
    sa.Column("cost_cache_creation_usd", sa.Numeric),
    sa.Column("cost_reasoning_usd", sa.Numeric),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("client_duration_ms", sa.Float, nullable=False),
    sa.Column("provider_duration_ms", sa.Float),
    sa.Column("proxy_overhead_ms", sa.Float),
    sa.Column("trace_id", sa.Text),
    sa.Column("span_id", sa.Text),
    sa.Index("model_call_call_id_idx", "call_id"),
    sa.Index("model_call_policy_idx", "policy_id"),
)

model_call_finish_reason = sa.Table(
    "model_call_finish_reason",
    metadata,
    _event_id("model_call"),
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("reason", sa.Text, nullable=False),
)

#: An object the call stored: a hop of the exchange, by its key in the
#: object store and the hash and size of what is there.
model_call_object = sa.Table(
    "model_call_object",
    metadata,
    _event_id("model_call"),
    sa.Column("position", sa.Integer, primary_key=True),
    sa.Column("hop", sa.Text, nullable=False),
    sa.Column("key", sa.Text, nullable=False),
    sa.Column("sha256", sa.Text, nullable=False),
    sa.Column("bytes", sa.BigInteger, nullable=False),
    sa.Column("encoding", sa.Text, nullable=False),
)

policy_check = sa.Table(
    "policy_check",
    metadata,
    _event_id(),
    sa.Column("policy_id", sa.Text, nullable=False),
    sa.Column("clause", sa.Text, nullable=False),
    sa.Column("finding_count", sa.Integer, nullable=False),
    # Null for a check recorded before its cost was.
    sa.Column("cost_usd", sa.Float),
)

review_grade = sa.Table(
    "review_grade",
    metadata,
    _event_id(),
    sa.Column("agent_id", sa.Text, nullable=False),
    sa.Column("detail", sa.Text, nullable=False),
    # Null where the write-up supports no verdict.
    sa.Column("status", sa.Text),
)


def _one(connection: sa.Connection, table: sa.Table, **row: object) -> None:
    connection.execute(insert(table).values(**row).on_conflict_do_nothing())


def _many(
    connection: sa.Connection,
    table: sa.Table,
    rows: Iterable[Mapping[str, object]],
) -> None:
    listed = list(rows)
    if listed:
        connection.execute(insert(table).on_conflict_do_nothing(), listed)


def _decimal(value: object) -> Decimal | None:
    return Decimal(value) if isinstance(value, str) else None


def _when(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def unpack_action(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    _one(
        connection,
        review_action,
        event_id=entry.event_id,
        action=p["action"],
        performed=p["performed"],
        status=p["status"],
        agent_id=p.get("agent_id"),
        comment_id=p.get("comment_id"),
        verdict=p.get("verdict"),
        head_sha=p.get("head_sha"),
        finding_count=p.get("finding_count"),
        raised_count=p.get("raised_count"),
        fixed_count=p.get("fixed_count"),
        dismissed_count=p.get("dismissed_count"),
        context=p.get("context"),
        state=p.get("state"),
        description=p.get("description"),
        label=p.get("label"),
    )
    _many(
        connection,
        review_action_removed_label,
        (
            {"event_id": entry.event_id, "label": label}
            for label in p.get("removed") or ()
        ),
    )


def unpack_dispatch(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    budget = p.get("budget") or {}
    cost = p.get("cost") or {}
    _one(
        connection,
        agent_dispatch,
        event_id=entry.event_id,
        agent_id=p["agent_id"],
        step=p["step"],
        runner=p.get("runner"),
        fingerprint=p.get("fingerprint"),
        remote_id=p.get("remote_id"),
        budget_usd=budget.get("usd"),
        budget_turns=budget.get("turns"),
        cost_usd=cost.get("usd"),
        cost_seconds=cost.get("seconds"),
        events=p.get("events"),
        detail=p.get("detail"),
        outcome=p.get("outcome"),
        write_up_id=p.get("write_up_id"),
        dispatched_at=_when(p.get("dispatched_at")),
        reason=p.get("reason"),
        reviewed_in=p.get("reviewed_in"),
    )
    _many(
        connection,
        agent_dispatch_withheld_file,
        (
            {"event_id": entry.event_id, "position": i, "path": path}
            for i, path in enumerate(p.get("withheld") or ())
        ),
    )


def _finding_row(entry: JournalEntry) -> dict[str, object]:
    p = entry.payload
    judge = p.get("judge") or {}
    return {
        "event_id": entry.event_id,
        "policy_id": p["policy_id"],
        "severity": p["severity"],
        "clause": p["clause"],
        "subject": p["subject"],
        "message": p["message"],
        "judged_by": p.get("judged_by"),
        "judge_model": judge.get("model"),
        "judge_fingerprint": judge.get("fingerprint"),
        "judge_prompt_hash": judge.get("prompt_hash"),
        "judge_input_hash": judge.get("input_hash"),
        "judge_exchange_id": judge.get("exchange_id"),
        "corpus_version": p.get("corpus_version"),
        "agent_id": p.get("agent_id"),
    }


def _raised_in_row(entry: JournalEntry) -> dict[str, object]:
    return {
        "raised_in_workflow_id": entry.payload["raised_in_workflow_id"],
        "raised_in_run_id": entry.payload["raised_in_run_id"],
    }


def unpack_raised(connection: sa.Connection, entry: JournalEntry) -> None:
    _one(connection, raised_finding, **_finding_row(entry))


def unpack_resolved(connection: sa.Connection, entry: JournalEntry) -> None:
    _one(
        connection,
        resolved_finding,
        **_finding_row(entry),
        **_raised_in_row(entry),
    )


def unpack_rewritten(connection: sa.Connection, entry: JournalEntry) -> None:
    _one(
        connection,
        rewritten_finding,
        **_finding_row(entry),
        **_raised_in_row(entry),
    )


def unpack_withheld(connection: sa.Connection, entry: JournalEntry) -> None:
    _one(
        connection,
        withheld_finding,
        **_finding_row(entry),
        share=entry.payload["share"],
    )


def unpack_invocation(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    identity = p.get("identity") or {}
    _one(
        connection,
        judge_invocation,
        event_id=entry.event_id,
        policy_id=p.get("policy_id"),
        status=p["status"],
        model=p.get("model"),
        finding_count=p["finding_count"],
        input_tokens=p["input_tokens"],
        output_tokens=p["output_tokens"],
        identity_model=identity.get("model"),
        identity_fingerprint=identity.get("fingerprint"),
        identity_prompt_hash=identity.get("prompt_hash"),
        identity_input_hash=identity.get("input_hash"),
        identity_exchange_id=identity.get("exchange_id"),
    )
    _many(
        connection,
        judge_invocation_unsupported,
        (
            {"event_id": entry.event_id, "position": i, "verdict": v}
            for i, v in enumerate(p.get("unsupported") or ())
        ),
    )


def unpack_call(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    _one(
        connection,
        model_call,
        event_id=entry.event_id,
        call_id=p["call_id"],
        archive_folder=p.get("archive_folder"),
        purpose=p["purpose"],
        policy_id=p.get("policy_id"),
        status=p["status"],
        http_status=p.get("http_status"),
        error=p.get("error"),
        requested_model=p["requested_model"],
        answered_model=p.get("answered_model"),
        model_id=p.get("model_id"),
        model_group=p.get("model_group"),
        api_base=p.get("api_base"),
        proxy_version=p.get("proxy_version"),
        attempt=p["attempt"],
        retries=p.get("retries"),
        fallbacks=p.get("fallbacks"),
        input_tokens=p.get("input_tokens"),
        output_tokens=p.get("output_tokens"),
        cached_input_tokens=p.get("cached_input_tokens"),
        cache_creation_input_tokens=p.get("cache_creation_input_tokens"),
        reasoning_output_tokens=p.get("reasoning_output_tokens"),
        total_tokens=p.get("total_tokens"),
        cost_usd=_decimal(p.get("cost_usd")),
        cost_nanodollars=p.get("cost_nanodollars"),
        cost_input_usd=_decimal(p.get("cost_input_usd")),
        cost_output_usd=_decimal(p.get("cost_output_usd")),
        cost_cache_read_usd=_decimal(p.get("cost_cache_read_usd")),
        cost_cache_creation_usd=_decimal(p.get("cost_cache_creation_usd")),
        cost_reasoning_usd=_decimal(p.get("cost_reasoning_usd")),
        started_at=_when(p["started_at"]),
        ended_at=_when(p["ended_at"]),
        client_duration_ms=p["client_duration_ms"],
        provider_duration_ms=p.get("provider_duration_ms"),
        proxy_overhead_ms=p.get("proxy_overhead_ms"),
        trace_id=p.get("trace_id"),
        span_id=p.get("span_id"),
    )
    _many(
        connection,
        model_call_finish_reason,
        (
            {"event_id": entry.event_id, "position": i, "reason": r}
            for i, r in enumerate(p.get("finish_reasons") or ())
        ),
    )
    _many(
        connection,
        model_call_object,
        (
            {
                "event_id": entry.event_id,
                "position": i,
                "hop": o["hop"],
                "key": o["key"],
                "sha256": o["sha256"],
                "bytes": o["bytes"],
                "encoding": o["encoding"],
            }
            for i, o in enumerate(p.get("objects") or ())
        ),
    )


def unpack_check(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    cost = p.get("cost") or {}
    _one(
        connection,
        policy_check,
        event_id=entry.event_id,
        policy_id=p["policy_id"],
        clause=p["clause"],
        finding_count=p["finding_count"],
        cost_usd=cost.get("usd"),
    )


def unpack_grade(connection: sa.Connection, entry: JournalEntry) -> None:
    p = entry.payload
    _one(
        connection,
        review_grade,
        event_id=entry.event_id,
        agent_id=p["agent_id"],
        detail=p["detail"],
        status=p.get("status"),
    )


Unpacker = Callable[[sa.Connection, JournalEntry], None]

#: What writes each review fact's typed rows, by event type.
UNPACKERS: Mapping[str, Unpacker] = {
    "action.taken": unpack_action,
    "agent.dispatched": unpack_dispatch,
    "finding.raised": unpack_raised,
    "finding.resolved": unpack_resolved,
    "finding.rewritten": unpack_rewritten,
    "finding.withheld": unpack_withheld,
    "judge.invoked": unpack_invocation,
    "llm.called": unpack_call,
    "policy.checked": unpack_check,
    "review.graded": unpack_grade,
}
