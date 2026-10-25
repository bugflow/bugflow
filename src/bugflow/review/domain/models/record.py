"""The record of one evaluation: everything it left in the journal, put
together.

A comment on a pull request shows only some of what an evaluation found.
The record has the rest: every finding and the clause it rests on, each
policy that ran and the exchange with the model behind it, what each
checkout agent's run cost, the verdict the grader gave, and what was
written to the pull request.

It is built from journal entries, each with the fact its typed table
holds (ADR 007), and stored exchanges, and nothing else. Something the
journal does not hold is left out, not guessed. Nothing here reads a
clock or a store: the entries are passed in.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.journal_facts import (
    AgentDispatch,
    JudgeInvocation,
    PolicyCheck,
    ResolvedFinding,
    ReviewAction,
    ReviewGrade,
)
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.domain.models.review_entry import ReviewEntry
from bugflow.shared.domain.values.correlation import Correlation

#: The order findings are listed in: the most severe first.
WEIGHT = {"fail": 0, "warn": 1, "info": 2}


@dataclass(frozen=True, kw_only=True)
class RecordedFinding:
    """One finding as the journal recorded it."""

    policy_id: str
    clause: str
    subject: str
    severity: str
    message: str
    judged_by: str | None = None
    agent_id: str | None = None
    corpus_version: str | None = None


@dataclass(frozen=True, kw_only=True)
class PolicyRun:
    """One run of one policy in the evaluation.

    For a judged policy this has the model that answered, the token
    counts and the exchange. For a checked policy ``status`` is
    "checked" and ``model`` is None.

    ``unsupported`` are verdicts the judge gave that were dropped
    because the words they quote are not in the submission.
    ``exchange`` is the stored request and response, or None if the
    judgement named no exchange or the store no longer has it.
    """

    policy_id: str
    status: str
    model: str | None = None
    finding_count: int = 0
    unsupported: tuple[str, ...] = ()
    input_tokens: int = 0
    output_tokens: int = 0
    agent_id: str | None = None
    corpus_version: str | None = None
    exchange_id: str | None = None
    exchange: JudgeExchange | None = None


@dataclass(frozen=True, kw_only=True)
class AgentRun:
    """What one checkout agent did in the evaluation.

    ``steps`` are the steps recorded for it, in order: "dispatched",
    "collected", "reused", "unavailable" or "no-worktree".
    ``runner`` and ``remote_id`` say where the run's own record is, and
    ``events`` how many events it has. ``withheld`` are the files the
    agent was not shown. ``reason`` says why there was no run, if there
    was none. ``verdict`` is the grader's verdict, or None if the
    write-up supported none, and ``grader_note`` is what the grader
    said.

    The write-up is not in the journal, so it is not here.
    """

    agent_id: str
    steps: tuple[str, ...] = ()
    runner: str = ""
    remote_id: str = ""
    fingerprint: str = ""
    events: int | None = None
    outcome: str = ""
    detail: str = ""
    cost: Mapping[str, float] = field(default_factory=dict)
    budget: Mapping[str, float] = field(default_factory=dict)
    withheld: tuple[str, ...] = ()
    reason: str = ""
    verdict: str | None = None
    grader_note: str = ""


@dataclass(frozen=True, kw_only=True)
class Said:
    """One comment the evaluation wrote to the pull request.

    ``agent_id`` is the reviewer whose findings the comment carried.
    ``performed`` is False if the comment was worked out and not
    written. The four counts are of findings: in the comment, newly
    raised, fixed since the last evaluation, and dismissed.
    """

    agent_id: str
    performed: bool = False
    status: str = ""
    comment_id: int | None = None
    verdict: str = ""
    findings: int = 0
    raised: int = 0
    fixed: int = 0
    dismissed: int = 0


@dataclass(frozen=True, kw_only=True)
class ReviewRecord:
    """The whole record of one evaluation.

    ``withdrawn`` are findings that an earlier evaluation raised and
    this one did not. ``label`` is the label the evaluation set on the
    pull request, or empty if it set none.
    """

    correlation: Correlation
    forge: str = ""
    repo: str = ""
    pr_number: int | None = None
    head_sha: str | None = None
    corpus_version: str | None = None
    findings: tuple[RecordedFinding, ...] = ()
    withdrawn: tuple[RecordedFinding, ...] = ()
    policies: tuple[PolicyRun, ...] = ()
    agents: tuple[AgentRun, ...] = ()
    said: tuple[Said, ...] = ()
    label: str = ""


def _finding(finding: Finding) -> RecordedFinding:
    """A finding as its journal entry's table holds it."""
    return RecordedFinding(
        policy_id=finding.policy_id,
        clause=finding.clause,
        subject=finding.subject,
        severity=finding.severity,
        message=finding.message,
        judged_by=finding.judged_by,
        agent_id=finding.agent_id,
        corpus_version=finding.corpus_version,
    )


def _ordered(
    findings: Iterable[RecordedFinding],
) -> tuple[RecordedFinding, ...]:
    """The findings sorted: the most severe first, then by policy, clause
    and subject.
    """
    return tuple(
        sorted(
            findings,
            key=lambda f: (
                WEIGHT.get(f.severity, len(WEIGHT)),
                f.policy_id,
                f.clause,
                f.subject,
            ),
        )
    )


def _judged(
    entry: ReviewEntry,
    judgement: JudgeInvocation,
    exchanges: Mapping[str, JudgeExchange],
) -> PolicyRun:
    """A judged policy's run, from its journal entry and the stored
    exchanges.
    """
    exchange_id = (
        judgement.identity.exchange_id if judgement.identity else None
    )
    return PolicyRun(
        policy_id=judgement.policy_id or "",
        status=judgement.status,
        model=judgement.model,
        finding_count=judgement.finding_count,
        unsupported=judgement.unsupported,
        input_tokens=judgement.input_tokens,
        output_tokens=judgement.output_tokens,
        agent_id=entry.agent_id,
        corpus_version=entry.corpus_version,
        exchange_id=exchange_id,
        exchange=exchanges.get(exchange_id) if exchange_id else None,
    )


def _checked(entry: ReviewEntry, check: PolicyCheck) -> PolicyRun:
    """A checked policy's run, from its journal entry."""
    return PolicyRun(
        policy_id=check.policy_id,
        status="checked",
        finding_count=check.finding_count,
        agent_id=entry.agent_id,
        corpus_version=entry.corpus_version,
    )


def _agent_run(agent_id: str, entries: Sequence[ReviewEntry]) -> AgentRun:
    """One checkout agent's run, from the entries recorded about it.

    Each entry says only what its step knew. Dispatching gives the
    runner, the fingerprint and the budget. Collecting gives the
    outcome and the cost. A later entry does not erase what an earlier
    one said.
    """
    steps: list[str] = []
    text = {
        "runner": "",
        "remote_id": "",
        "fingerprint": "",
        "outcome": "",
        "detail": "",
        "reason": "",
    }
    events: int | None = None
    cost: dict[str, float] = {}
    budget: dict[str, float] = {}
    withheld: tuple[str, ...] = ()
    verdict: str | None = None
    grader_note = ""
    for entry in entries:
        fact = entry.fact
        if isinstance(fact, ReviewGrade):
            verdict = fact.status
            grader_note = fact.detail or ""
            continue
        if not isinstance(fact, AgentDispatch):
            continue
        steps.append(fact.step)
        for name in text:
            value = getattr(fact, name)
            if value:
                text[name] = str(value)
        recorded_cost = _figures(
            ("usd", fact.cost_usd), ("seconds", fact.cost_seconds)
        )
        if recorded_cost:
            cost = recorded_cost
        recorded_budget = _figures(
            ("usd", fact.budget_usd), ("turns", fact.budget_turns)
        )
        if recorded_budget:
            budget = recorded_budget
        if fact.withheld:
            withheld = fact.withheld
        if fact.events is not None:
            events = fact.events
        if fact.step == "reused":
            text["reason"] = (
                "reviewed already at this commit, in run "
                f"{fact.reviewed_in or ''}"
            )
    return AgentRun(
        agent_id=agent_id,
        steps=tuple(steps),
        events=events,
        cost=cost,
        budget=budget,
        withheld=withheld,
        verdict=verdict,
        grader_note=grader_note,
        **text,
    )


def _figures(*named: tuple[str, float | None]) -> dict[str, float]:
    """The figures recorded, by name, leaving out those that were not."""
    return {name: value for name, value in named if value is not None}


def _said(action: ReviewAction) -> Said:
    """A comment, from its journal entry's row."""
    return Said(
        agent_id=action.agent_id or "",
        performed=action.performed,
        status=action.status,
        comment_id=action.comment_id,
        verdict=action.verdict or "",
        findings=action.finding_count or 0,
        raised=action.raised_count or 0,
        fixed=action.fixed_count or 0,
        dismissed=action.dismissed_count or 0,
    )


def _actions(rows: Sequence[ReviewEntry], action: str) -> list[ReviewAction]:
    """The actions of one kind, in the order recorded."""
    return [
        e.fact
        for e in rows
        if isinstance(e.fact, ReviewAction) and e.fact.action == action
    ]


def review_record(
    correlation: Correlation,
    entries: Iterable[ReviewEntry],
    exchanges: Mapping[str, JudgeExchange] | None = None,
) -> ReviewRecord:
    """Build the record of one evaluation.

    ``entries`` are the journal entries of that evaluation, oldest
    first, each with the fact its table holds. ``exchanges`` are the
    stored judge exchanges that its judgements name, by exchange id.
    """
    rows = list(entries)
    archived = exchanges or {}
    by_agent: dict[str, list[ReviewEntry]] = {}
    for entry in rows:
        if isinstance(entry.fact, AgentDispatch | ReviewGrade):
            agent_id = entry.fact.agent_id or entry.agent_id or ""
            by_agent.setdefault(agent_id, []).append(entry)
    label = next((a.label or "" for a in _actions(rows, "outcome_label")), "")
    first = rows[0] if rows else None
    return ReviewRecord(
        correlation=correlation,
        forge=first.forge if first else "",
        repo=first.repo if first else "",
        pr_number=first.pr_number if first else None,
        head_sha=next((e.commit_sha for e in rows if e.commit_sha), None),
        # An entry with no agent has the evaluation's own corpus
        # version. An entry with an agent has that reviewer's.
        corpus_version=next(
            (e.corpus_version for e in rows if e.agent_id is None),
            None,
        ),
        findings=_ordered(
            _finding(e.fact) for e in rows if isinstance(e.fact, Finding)
        ),
        withdrawn=_ordered(
            _finding(e.fact.finding)
            for e in rows
            if isinstance(e.fact, ResolvedFinding)
        ),
        policies=tuple(
            sorted(
                (
                    _judged(e, e.fact, archived)
                    if isinstance(e.fact, JudgeInvocation)
                    else _checked(e, e.fact)
                    for e in rows
                    if isinstance(e.fact, JudgeInvocation | PolicyCheck)
                ),
                key=lambda p: p.policy_id,
            )
        ),
        agents=tuple(
            _agent_run(agent_id, by_agent[agent_id])
            for agent_id in sorted(by_agent)
        ),
        said=tuple(
            sorted(
                (_said(a) for a in _actions(rows, "review_comment")),
                key=lambda s: s.agent_id,
            )
        ),
        label=label,
    )
