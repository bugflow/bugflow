"""The scope and stored facts of a bounded history read."""

from dataclasses import dataclass
from datetime import datetime

from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation


@dataclass(frozen=True, kw_only=True)
class HistoryLimits:
    """Limits supplied by the caller that assembles the reader."""

    max_events: int = 10_000
    max_bytes: int = 8 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_events < 1 or self.max_bytes < 1:
            raise ValueError("history limits must be positive")


@dataclass(frozen=True, kw_only=True)
class HistoryScope:
    """One repository and an explicit set of pull requests to read."""

    forge: str
    repo: str
    pr_numbers: tuple[int, ...]
    correlation: Correlation | None = None

    def __post_init__(self) -> None:
        if not self.forge.strip() or len(self.repo.split("/")) != 2:
            raise ValueError("a forge and owner/repository are required")
        if any(not part.strip() for part in self.repo.split("/")):
            raise ValueError("an owner and repository are required")
        if not self.pr_numbers or any(n < 1 for n in self.pr_numbers):
            raise ValueError("positive pull-request numbers are required")
        object.__setattr__(
            self, "pr_numbers", tuple(sorted(set(self.pr_numbers)))
        )


@dataclass(frozen=True, kw_only=True)
class StoredReviewEvent:
    """A journal fact with the metadata recorded by its storage adapter.

    Deployment stamps name the writer's deployment. They do not assert
    that a fact belongs to an individual policy in that deployment.
    """

    entry: JournalEntry
    recorded_at: datetime | None = None
    policy_repository: str | None = None
    policy_commit: str | None = None
    policy_content: str | None = None


@dataclass(frozen=True, kw_only=True)
class RecordedModelCost:
    """Only recorded model calls contribute; retries can be absent."""

    nanodollars: int
    priced_calls: int
    unpriced_calls: int
    event_ids: tuple[str, ...]
    call_ids: tuple[str, ...]
    completeness: str = "unknown"


@dataclass(frozen=True, kw_only=True)
class ContentReference:
    """A reference in a fact; this read does not open linked content."""

    kind: str
    source_event_id: str
    content_id: str | None
    availability: str


@dataclass(frozen=True, kw_only=True)
class ObservedPolicy:
    policy_id: str
    judgement_event_ids: tuple[str, ...]
    judgement_statuses: tuple[str, ...]
    checked_event_ids: tuple[str, ...]
    answered: bool
    raised_event_ids: tuple[str, ...]
    model_cost: RecordedModelCost


@dataclass(frozen=True, kw_only=True)
class ObservedReviewRun:
    pr_number: int
    correlation: Correlation
    events: tuple[StoredReviewEvent, ...]
    policies: tuple[ObservedPolicy, ...]
    model_cost: RecordedModelCost
    requested_policy_cost: RecordedModelCost | None
    content_references: tuple[ContentReference, ...]
    completion: str = "unknown"


def recorded_model_cost(
    events: tuple[StoredReviewEvent, ...], policy_id: str | None = None
) -> RecordedModelCost:
    calls = tuple(
        event.entry
        for event in events
        if event.entry.event_type == "llm.called"
        and (
            policy_id is None
            or event.entry.payload.get("policy_id") == policy_id
        )
    )
    costs = tuple(call.payload.get("cost_nanodollars") for call in calls)
    priced = tuple(cost for cost in costs if type(cost) is int)
    return RecordedModelCost(
        nanodollars=sum(priced),
        priced_calls=len(priced),
        unpriced_calls=len(calls) - len(priced),
        event_ids=tuple(str(call.event_id) for call in calls),
        call_ids=tuple(
            str(call.payload["call_id"])
            for call in calls
            if call.payload.get("call_id") is not None
        ),
    )


def observed_review_run(
    events: tuple[StoredReviewEvent, ...], policy_id: str | None
) -> ObservedReviewRun:
    """Project one run without inferring completion or publication."""
    first = events[0].entry
    assert first.pr_number is not None
    policy_ids = {
        str(event.entry.payload["policy_id"])
        for event in events
        if event.entry.payload.get("policy_id") is not None
    }
    if policy_id is not None:
        policy_ids.add(policy_id)
    policies = []
    for name in sorted(policy_ids):
        judgements = tuple(
            event.entry
            for event in events
            if event.entry.event_type == "judge.invoked"
            and event.entry.payload.get("policy_id") == name
        )
        checked = tuple(
            event.entry
            for event in events
            if event.entry.event_type == "policy.checked"
            and event.entry.payload.get("policy_id") == name
        )
        statuses = tuple(
            str(j.payload.get("status") or "") for j in judgements
        )
        policies.append(
            ObservedPolicy(
                policy_id=name,
                judgement_event_ids=tuple(str(j.event_id) for j in judgements),
                judgement_statuses=statuses,
                checked_event_ids=tuple(
                    str(check.event_id) for check in checked
                ),
                answered=bool(checked)
                or any(status.startswith("judged by") for status in statuses),
                raised_event_ids=tuple(
                    str(event.entry.event_id)
                    for event in events
                    if event.entry.event_type == "finding.raised"
                    and event.entry.payload.get("policy_id") == name
                ),
                model_cost=recorded_model_cost(events, name),
            )
        )
    references = []
    for event in events:
        entry = event.entry
        named: tuple[tuple[str, object], ...] = ()
        if entry.event_type == "pr.observed":
            named = (("snapshot", entry.payload.get("snapshot_id")),)
        elif entry.event_type == "judge.invoked":
            identity = entry.payload.get("identity") or {}
            named = (
                ("snapshot", identity.get("input_hash")),
                ("exchange", identity.get("exchange_id")),
            )
        for kind, content_id in named:
            references.append(
                ContentReference(
                    kind=kind,
                    source_event_id=str(entry.event_id),
                    content_id=str(content_id) if content_id else None,
                    availability="not_checked"
                    if content_id
                    else "not_recorded",
                )
            )
    return ObservedReviewRun(
        pr_number=first.pr_number,
        correlation=Correlation(
            workflow_id=first.workflow_id, run_id=first.run_id
        ),
        events=events,
        policies=tuple(policies),
        model_cost=recorded_model_cost(events),
        requested_policy_cost=(
            recorded_model_cost(events, policy_id)
            if policy_id is not None
            else None
        ),
        content_references=tuple(references),
    )
