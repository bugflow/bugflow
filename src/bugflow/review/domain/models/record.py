"""The record of one evaluation: everything it left in the journal, put
together.

A comment on a pull request shows only some of what an evaluation found.
The record has the rest: every finding and the clause it rests on, each
policy that ran and the exchange with the model behind it, what each
checkout agent's run cost, the verdict the grader gave, and what was
written to the pull request.

It is built from journal entries and stored exchanges and nothing else.
Something the journal does not hold is left out, not guessed. Nothing
here reads a clock or a store: the entries are passed in.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from bugflow.review.domain.facts import (
    ACTION_TAKEN,
    AGENT_DISPATCHED,
    FINDING_RAISED,
    FINDING_RESOLVED,
    JUDGE_INVOKED,
    POLICY_CHECKED,
    REVIEW_GRADED,
)
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.shared.domain.models.journal_entry import JournalEntry
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


def _finding(payload: Mapping[str, object]) -> RecordedFinding:
    """A finding from the payload of its journal entry."""
    return RecordedFinding(
        policy_id=str(payload.get("policy_id", "")),
        clause=str(payload.get("clause", "")),
        subject=str(payload.get("subject", "")),
        severity=str(payload.get("severity", "")),
        message=str(payload.get("message", "")),
        judged_by=_text_or_none(payload.get("judged_by")),
        agent_id=_text_or_none(payload.get("agent_id")),
        corpus_version=_text_or_none(payload.get("corpus_version")),
    )


def _text_or_none(value: object) -> str | None:
    return None if value is None else str(value)


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
    entry: JournalEntry, exchanges: Mapping[str, JudgeExchange]
) -> PolicyRun:
    """A judged policy's run, from its journal entry and the stored
    exchanges.
    """
    payload = entry.payload
    identity = payload.get("identity") or {}
    exchange_id = _text_or_none(identity.get("exchange_id"))
    return PolicyRun(
        policy_id=str(payload.get("policy_id") or ""),
        status=str(payload.get("status", "")),
        model=_text_or_none(payload.get("model")),
        finding_count=int(payload.get("finding_count") or 0),
        unsupported=tuple(str(u) for u in payload.get("unsupported") or ()),
        input_tokens=int(payload.get("input_tokens") or 0),
        output_tokens=int(payload.get("output_tokens") or 0),
        agent_id=entry.agent_id,
        corpus_version=entry.corpus_version,
        exchange_id=exchange_id,
        exchange=exchanges.get(exchange_id) if exchange_id else None,
    )


def _checked(entry: JournalEntry) -> PolicyRun:
    """A checked policy's run, from its journal entry."""
    payload = entry.payload
    return PolicyRun(
        policy_id=str(payload.get("policy_id") or ""),
        status="checked",
        finding_count=int(payload.get("finding_count") or 0),
        agent_id=entry.agent_id,
        corpus_version=entry.corpus_version,
    )


def _agent_run(agent_id: str, entries: Sequence[JournalEntry]) -> AgentRun:
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
        payload = entry.payload
        if entry.event_type == REVIEW_GRADED:
            verdict = _text_or_none(payload.get("status"))
            grader_note = str(payload.get("detail") or "")
            continue
        step = str(payload.get("step", ""))
        steps.append(step)
        for name in text:
            if payload.get(name):
                text[name] = str(payload[name])
        if payload.get("cost"):
            cost = {k: float(v) for k, v in dict(payload["cost"]).items()}
        if payload.get("budget"):
            budget = {k: float(v) for k, v in dict(payload["budget"]).items()}
        if payload.get("withheld"):
            withheld = tuple(str(w) for w in payload["withheld"])
        if payload.get("events") is not None:
            events = int(payload["events"])
        if step == "reused":
            text["reason"] = (
                "reviewed already at this commit, in run "
                f"{payload.get('reviewed_in', '')}"
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


def _said(entry: JournalEntry) -> Said:
    """A comment, from its journal entry."""
    payload = entry.payload
    comment_id = payload.get("comment_id")
    return Said(
        agent_id=str(payload.get("agent_id", "")),
        performed=bool(payload.get("performed")),
        status=str(payload.get("status", "")),
        comment_id=None if comment_id is None else int(comment_id),
        verdict=str(payload.get("verdict") or ""),
        findings=int(payload.get("finding_count") or 0),
        raised=int(payload.get("raised_count") or 0),
        fixed=int(payload.get("fixed_count") or 0),
        dismissed=int(payload.get("dismissed_count") or 0),
    )


def review_record(
    correlation: Correlation,
    entries: Iterable[JournalEntry],
    exchanges: Mapping[str, JudgeExchange] | None = None,
) -> ReviewRecord:
    """Build the record of one evaluation.

    ``entries`` are the journal entries of that evaluation, oldest
    first. ``exchanges`` are the stored judge exchanges that its
    judgements name, by exchange id.
    """
    rows = list(entries)
    archived = exchanges or {}
    by_agent: dict[str, list[JournalEntry]] = {}
    for entry in rows:
        if entry.event_type in (AGENT_DISPATCHED, REVIEW_GRADED):
            agent_id = str(entry.payload.get("agent_id") or entry.agent_id)
            by_agent.setdefault(agent_id, []).append(entry)
    label = next(
        (
            str(e.payload.get("label") or "")
            for e in rows
            if e.event_type == ACTION_TAKEN
            and e.payload.get("action") == "outcome_label"
        ),
        "",
    )
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
            _finding(e.payload) for e in rows if e.event_type == FINDING_RAISED
        ),
        withdrawn=_ordered(
            _finding(e.payload)
            for e in rows
            if e.event_type == FINDING_RESOLVED
        ),
        policies=tuple(
            sorted(
                (
                    _judged(e, archived)
                    if e.event_type == JUDGE_INVOKED
                    else _checked(e)
                    for e in rows
                    if e.event_type in (JUDGE_INVOKED, POLICY_CHECKED)
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
                (
                    _said(e)
                    for e in rows
                    if e.event_type == ACTION_TAKEN
                    and e.payload.get("action") == "review_comment"
                ),
                key=lambda s: s.agent_id,
            )
        ),
        label=label,
    )
