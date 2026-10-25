"""The review's facts as their tables hold them (ADR 007).

Each class here is one row of the table named for it: a ``ReviewAction``
is a row of ``review_action``, an ``AgentDispatch`` of
``agent_dispatch``, and so on. A raised finding's row is a ``Finding``.
A resolved, rewritten or withheld finding carries the finding and what
its own table adds. A fact's child rows, the labels an action removed,
the files a dispatch withheld, the verdicts a judgement dropped and a
call's finish reasons and stored objects, are tuples in their order.

The Postgres adapter builds these from the typed tables, and the
in-memory journal from the payload the entry was written with, through
``fact_from_payload``, so a test's entry carries what the table takes.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, TypeVar

from bugflow.review.domain.facts import (
    ACTION_TAKEN,
    AGENT_DISPATCHED,
    FINDING_RAISED,
    FINDING_RESOLVED,
    FINDING_REWRITTEN,
    FINDING_WITHHELD,
    JUDGE_INVOKED,
    LLM_CALLED,
    POLICY_CHECKED,
    REVIEW_GRADED,
)
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.judgement import JudgeIdentity
from bugflow.shared.domain.values.correlation import Correlation


@dataclass(frozen=True, kw_only=True)
class ReviewAction:
    """An action on the pull request: a review comment, a commit status
    or an outcome label. ``action`` says which, and the columns the
    other actions do not carry are None."""

    action: str
    performed: bool
    status: str
    agent_id: str | None = None
    comment_id: int | None = None
    verdict: str | None = None
    head_sha: str | None = None
    finding_count: int | None = None
    raised_count: int | None = None
    fixed_count: int | None = None
    dismissed_count: int | None = None
    context: str | None = None
    state: str | None = None
    description: str | None = None
    label: str | None = None
    #: The labels an outcome label replaced.
    removed: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class AgentDispatch:
    """A step of a checkout agent's dispatch, named by ``step``."""

    agent_id: str
    step: str
    runner: str | None = None
    fingerprint: str | None = None
    remote_id: str | None = None
    budget_usd: float | None = None
    budget_turns: float | None = None
    cost_usd: float | None = None
    cost_seconds: float | None = None
    events: int | None = None
    detail: str | None = None
    outcome: str | None = None
    write_up_id: str | None = None
    dispatched_at: datetime | None = None
    reason: str | None = None
    reviewed_in: str | None = None
    #: The files the agent was not shown.
    withheld: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ResolvedFinding:
    """A finding an earlier evaluation raised that this one did not."""

    finding: Finding
    raised_in: Correlation


@dataclass(frozen=True, kw_only=True)
class RewrittenFinding:
    """A finding whose quoted words are gone from the pull request."""

    finding: Finding
    raised_in: Correlation


@dataclass(frozen=True, kw_only=True)
class WithheldFinding:
    """A warning kept out of the pull request, and the share of warnings
    being kept out when it was."""

    finding: Finding
    share: float


@dataclass(frozen=True, kw_only=True)
class JudgeInvocation:
    """A judge was asked about one policy, and how it went."""

    policy_id: str | None
    status: str
    model: str | None
    finding_count: int
    input_tokens: int
    output_tokens: int
    #: Enough to run the judgement again, or None where the judge
    #: recorded none.
    identity: JudgeIdentity | None
    #: The verdicts the judge gave that were dropped because the words
    #: they quote are not in the submission.
    unsupported: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class StoredObject:
    """A hop of a call's exchange, by its key in the object store and the
    hash and size of what is there."""

    hop: str
    key: str
    sha256: str
    bytes: int
    encoding: str


@dataclass(frozen=True, kw_only=True)
class ModelCall:
    """One call to a language model."""

    call_id: str
    purpose: str
    status: str
    requested_model: str
    attempt: int
    started_at: datetime
    ended_at: datetime
    client_duration_ms: float
    archive_folder: str | None = None
    policy_id: str | None = None
    http_status: int | None = None
    error: str | None = None
    answered_model: str | None = None
    model_id: str | None = None
    model_group: str | None = None
    api_base: str | None = None
    proxy_version: str | None = None
    retries: int | None = None
    fallbacks: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: Decimal | None = None
    cost_nanodollars: int | None = None
    cost_input_usd: Decimal | None = None
    cost_output_usd: Decimal | None = None
    cost_cache_read_usd: Decimal | None = None
    cost_cache_creation_usd: Decimal | None = None
    cost_reasoning_usd: Decimal | None = None
    provider_duration_ms: float | None = None
    proxy_overhead_ms: float | None = None
    trace_id: str | None = None
    span_id: str | None = None
    finish_reasons: tuple[str, ...] = ()
    objects: tuple[StoredObject, ...] = ()


@dataclass(frozen=True, kw_only=True)
class PolicyCheck:
    """A checked policy's run."""

    policy_id: str
    clause: str
    finding_count: int
    cost_usd: float | None = None


@dataclass(frozen=True, kw_only=True)
class ReviewGrade:
    """A grader's verdict on a checkout agent's write-up: ``status`` is
    None where the write-up supports none."""

    agent_id: str
    detail: str
    status: str | None = None


ReviewFact = (
    Finding
    | ResolvedFinding
    | RewrittenFinding
    | WithheldFinding
    | JudgeInvocation
    | ModelCall
    | PolicyCheck
    | ReviewGrade
    | AgentDispatch
    | ReviewAction
)

F = TypeVar("F")


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def _integer(value: object) -> int | None:
    return None if value is None else int(value)  # type: ignore[call-overload]


def _number(value: object) -> float | None:
    return None if value is None else float(value)  # type: ignore[arg-type]


def _decimal(value: object) -> Decimal | None:
    return Decimal(value) if isinstance(value, str) else None


def _when(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def _strings(value: object) -> tuple[str, ...]:
    return tuple(str(v) for v in value) if isinstance(value, list) else ()


def _identity(value: object) -> JudgeIdentity | None:
    if not isinstance(value, Mapping) or not value:
        return None
    return JudgeIdentity(
        model=str(value["model"]),
        fingerprint=str(value["fingerprint"]),
        prompt_hash=_text(value.get("prompt_hash")),
        input_hash=str(value["input_hash"]),
        exchange_id=_text(value.get("exchange_id")),
    )


def _raised_in(p: Mapping[str, Any]) -> Correlation:
    return Correlation(
        workflow_id=str(p["raised_in_workflow_id"]),
        run_id=str(p["raised_in_run_id"]),
    )


def _action(p: Mapping[str, Any]) -> ReviewAction:
    return ReviewAction(
        action=str(p["action"]),
        performed=bool(p["performed"]),
        status=str(p["status"]),
        agent_id=_text(p.get("agent_id")),
        comment_id=_integer(p.get("comment_id")),
        verdict=_text(p.get("verdict")),
        head_sha=_text(p.get("head_sha")),
        finding_count=_integer(p.get("finding_count")),
        raised_count=_integer(p.get("raised_count")),
        fixed_count=_integer(p.get("fixed_count")),
        dismissed_count=_integer(p.get("dismissed_count")),
        context=_text(p.get("context")),
        state=_text(p.get("state")),
        description=_text(p.get("description")),
        label=_text(p.get("label")),
        removed=_strings(p.get("removed")),
    )


def _dispatch(p: Mapping[str, Any]) -> AgentDispatch:
    budget = p.get("budget") or {}
    cost = p.get("cost") or {}
    return AgentDispatch(
        agent_id=str(p["agent_id"]),
        step=str(p["step"]),
        runner=_text(p.get("runner")),
        fingerprint=_text(p.get("fingerprint")),
        remote_id=_text(p.get("remote_id")),
        budget_usd=_number(budget.get("usd")),
        budget_turns=_number(budget.get("turns")),
        cost_usd=_number(cost.get("usd")),
        cost_seconds=_number(cost.get("seconds")),
        events=_integer(p.get("events")),
        detail=_text(p.get("detail")),
        outcome=_text(p.get("outcome")),
        write_up_id=_text(p.get("write_up_id")),
        dispatched_at=_when(p.get("dispatched_at")),
        reason=_text(p.get("reason")),
        reviewed_in=_text(p.get("reviewed_in")),
        withheld=_strings(p.get("withheld")),
    )


def _invocation(p: Mapping[str, Any]) -> JudgeInvocation:
    return JudgeInvocation(
        policy_id=_text(p.get("policy_id")),
        status=str(p["status"]),
        model=_text(p.get("model")),
        finding_count=int(p["finding_count"]),
        input_tokens=int(p["input_tokens"]),
        output_tokens=int(p["output_tokens"]),
        identity=_identity(p.get("identity")),
        unsupported=_strings(p.get("unsupported")),
    )


def _call(p: Mapping[str, Any]) -> ModelCall:
    started_at = _when(p["started_at"])
    ended_at = _when(p["ended_at"])
    assert started_at is not None and ended_at is not None
    return ModelCall(
        call_id=str(p["call_id"]),
        purpose=str(p["purpose"]),
        status=str(p["status"]),
        requested_model=str(p["requested_model"]),
        attempt=int(p["attempt"]),
        started_at=started_at,
        ended_at=ended_at,
        client_duration_ms=float(p["client_duration_ms"]),
        archive_folder=_text(p.get("archive_folder")),
        policy_id=_text(p.get("policy_id")),
        http_status=_integer(p.get("http_status")),
        error=_text(p.get("error")),
        answered_model=_text(p.get("answered_model")),
        model_id=_text(p.get("model_id")),
        model_group=_text(p.get("model_group")),
        api_base=_text(p.get("api_base")),
        proxy_version=_text(p.get("proxy_version")),
        retries=_integer(p.get("retries")),
        fallbacks=_integer(p.get("fallbacks")),
        input_tokens=_integer(p.get("input_tokens")),
        output_tokens=_integer(p.get("output_tokens")),
        cached_input_tokens=_integer(p.get("cached_input_tokens")),
        cache_creation_input_tokens=_integer(
            p.get("cache_creation_input_tokens")
        ),
        reasoning_output_tokens=_integer(p.get("reasoning_output_tokens")),
        total_tokens=_integer(p.get("total_tokens")),
        cost_usd=_decimal(p.get("cost_usd")),
        cost_nanodollars=_integer(p.get("cost_nanodollars")),
        cost_input_usd=_decimal(p.get("cost_input_usd")),
        cost_output_usd=_decimal(p.get("cost_output_usd")),
        cost_cache_read_usd=_decimal(p.get("cost_cache_read_usd")),
        cost_cache_creation_usd=_decimal(p.get("cost_cache_creation_usd")),
        cost_reasoning_usd=_decimal(p.get("cost_reasoning_usd")),
        provider_duration_ms=_number(p.get("provider_duration_ms")),
        proxy_overhead_ms=_number(p.get("proxy_overhead_ms")),
        trace_id=_text(p.get("trace_id")),
        span_id=_text(p.get("span_id")),
        finish_reasons=_strings(p.get("finish_reasons")),
        objects=tuple(
            StoredObject(
                hop=str(o["hop"]),
                key=str(o["key"]),
                sha256=str(o["sha256"]),
                bytes=int(o["bytes"]),
                encoding=str(o["encoding"]),
            )
            for o in p.get("objects") or ()
        ),
    )


def _check(p: Mapping[str, Any]) -> PolicyCheck:
    cost = p.get("cost") or {}
    return PolicyCheck(
        policy_id=str(p["policy_id"]),
        clause=str(p["clause"]),
        finding_count=int(p["finding_count"]),
        cost_usd=_number(cost.get("usd")),
    )


def _grade(p: Mapping[str, Any]) -> ReviewGrade:
    return ReviewGrade(
        agent_id=str(p["agent_id"]),
        detail=str(p["detail"]),
        status=_text(p.get("status")),
    )


def fact_from_payload(
    event_type: str, payload: Mapping[str, Any]
) -> ReviewFact | None:
    """The fact a payload of this type holds, as its table would hold it,
    or None for a type this context has no table for."""
    if event_type == FINDING_RAISED:
        return Finding.from_payload(payload)
    if event_type == FINDING_RESOLVED:
        return ResolvedFinding(
            finding=Finding.from_payload(payload),
            raised_in=_raised_in(payload),
        )
    if event_type == FINDING_REWRITTEN:
        return RewrittenFinding(
            finding=Finding.from_payload(payload),
            raised_in=_raised_in(payload),
        )
    if event_type == FINDING_WITHHELD:
        return WithheldFinding(
            finding=Finding.from_payload(payload),
            share=float(payload["share"]),
        )
    if event_type == JUDGE_INVOKED:
        return _invocation(payload)
    if event_type == LLM_CALLED:
        return _call(payload)
    if event_type == POLICY_CHECKED:
        return _check(payload)
    if event_type == REVIEW_GRADED:
        return _grade(payload)
    if event_type == AGENT_DISPATCHED:
        return _dispatch(payload)
    if event_type == ACTION_TAKEN:
        return _action(payload)
    return None


def policy_of(fact: ReviewFact | None) -> str | None:
    """The policy a fact is about, or None where it names none."""
    if isinstance(fact, Finding):
        return fact.policy_id
    if isinstance(fact, ResolvedFinding | RewrittenFinding | WithheldFinding):
        return fact.finding.policy_id
    if isinstance(fact, JudgeInvocation | ModelCall | PolicyCheck):
        return fact.policy_id
    return None
