"""The scope and stored facts of a bounded history read."""

from dataclasses import dataclass
from datetime import datetime

from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.journal_facts import (
    JudgeInvocation,
    ModelCall,
    PolicyCheck,
    policy_of,
)
from bugflow.review.domain.models.review_entry import ReviewEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.repository_origin import RepositoryOrigin


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
    origin: str | None = None

    def __post_init__(self) -> None:
        if self.origin is not None:
            canonical = RepositoryOrigin(self.origin)
            if "/".join(str(canonical).split("/")[1:]) != self.repo:
                raise ValueError("origin must name the selected repository")
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

    #: The entry, with the review fact its typed table holds (ADR 007).
    entry: ReviewEntry
    recorded_at: datetime | None = None
    policy_repository: str | None = None
    policy_commit: str | None = None
    policy_content: str | None = None
    #: For a ``pr.observed`` fact, the stored submission the observation
    #: read, from the observation's own row (ADR 007). None otherwise.
    snapshot_id: str | None = None


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
        (event.entry, event.entry.fact)
        for event in events
        if isinstance(event.entry.fact, ModelCall)
        and (policy_id is None or event.entry.fact.policy_id == policy_id)
    )
    costs = tuple(call.cost_nanodollars for _, call in calls)
    priced = tuple(cost for cost in costs if type(cost) is int)
    return RecordedModelCost(
        nanodollars=sum(priced),
        priced_calls=len(priced),
        unpriced_calls=len(calls) - len(priced),
        event_ids=tuple(str(entry.event_id) for entry, _ in calls),
        call_ids=tuple(call.call_id for _, call in calls),
    )


def observed_review_run(
    events: tuple[StoredReviewEvent, ...], policy_id: str | None
) -> ObservedReviewRun:
    """Project one run without inferring completion or publication."""
    first = events[0].entry
    assert first.pr_number is not None
    policy_ids = {
        policy
        for event in events
        if (policy := policy_of(event.entry.fact)) is not None
    }
    if policy_id is not None:
        policy_ids.add(policy_id)
    policies = []
    for name in sorted(policy_ids):
        judgements = tuple(
            (event.entry, event.entry.fact)
            for event in events
            if isinstance(event.entry.fact, JudgeInvocation)
            and event.entry.fact.policy_id == name
        )
        checked = tuple(
            event.entry
            for event in events
            if isinstance(event.entry.fact, PolicyCheck)
            and event.entry.fact.policy_id == name
        )
        statuses = tuple(judgement.status or "" for _, judgement in judgements)
        policies.append(
            ObservedPolicy(
                policy_id=name,
                judgement_event_ids=tuple(
                    str(entry.event_id) for entry, _ in judgements
                ),
                judgement_statuses=statuses,
                checked_event_ids=tuple(
                    str(check.event_id) for check in checked
                ),
                answered=bool(checked)
                or any(status.startswith("judged by") for status in statuses),
                raised_event_ids=tuple(
                    str(event.entry.event_id)
                    for event in events
                    if isinstance(event.entry.fact, Finding)
                    and event.entry.fact.policy_id == name
                ),
                model_cost=recorded_model_cost(events, name),
            )
        )
    references = []
    for event in events:
        entry = event.entry
        named: tuple[tuple[str, object], ...] = ()
        if entry.event_type == "pr.observed":
            named = (("snapshot", event.snapshot_id),)
        elif isinstance(entry.fact, JudgeInvocation):
            identity = entry.fact.identity
            named = (
                ("snapshot", identity.input_hash if identity else None),
                ("exchange", identity.exchange_id if identity else None),
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
