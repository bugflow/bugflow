"""A bounded history preserves the evidence needed to inspect a review."""

from datetime import UTC, datetime
from typing import Any

import pytest

from bugflow.review.domain.errors import HistoryTooLargeError
from bugflow.review.domain.models.history import (
    HistoryLimits,
    HistoryScope,
    StoredReviewEvent,
)
from bugflow.review.dtos.read_review_record import (
    ReadReviewHistoryRequest,
    ReadReviewHistoryResponse,
)
from bugflow.review.infrastructure.in_memory_history import InMemoryHistory
from bugflow.review.usecases.read_review_record import ReadReviewHistoryUseCase
from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.values.correlation import Correlation

NOW = datetime(2026, 10, 18, tzinfo=UTC)
SCOPE = HistoryScope(forge="github", repo="owner/repo", pr_numbers=(30, 31))


def fact(
    kind: str,
    key: str,
    payload: dict[str, Any],
    *,
    run: str = "one",
    repo: str = "owner/repo",
    pr: int = 30,
) -> StoredReviewEvent:
    correlation = Correlation(workflow_id="evaluation", run_id=run)
    return StoredReviewEvent(
        entry=JournalEntry(
            event_id=event_id(correlation, kind, key),
            occurred_at=NOW,
            event_type=kind,
            forge="github",
            repo=repo,
            pr_number=pr,
            commit_sha="same-head",
            corpus_version="corpus",
            workflow_id="evaluation",
            run_id=run,
            payload=payload,
            agent_id="reviewer",
            build="build",
        ),
        recorded_at=NOW,
        policy_repository="policies/repo",
        policy_commit="policy-sha",
        policy_content="policy-hash",
    )


def read(
    events: list[StoredReviewEvent],
    *,
    policy_id: str | None = "ED-02",
    limits: HistoryLimits | None = None,
) -> ReadReviewHistoryResponse:
    return ReadReviewHistoryUseCase(
        InMemoryHistory(events), limits or HistoryLimits()
    ).execute(ReadReviewHistoryRequest(scope=SCOPE, policy_id=policy_id))


def test_repeated_evaluations_keep_their_input_and_provenance() -> None:
    first = fact("pr.observed", "snapshot", {"snapshot_id": "before"})
    second = fact(
        "pr.observed", "snapshot", {"snapshot_id": "after"}, run="two"
    )
    result = read([second, first, first])
    assert result.event_count == 2
    assert result.observed_pr_numbers == (30,)
    assert result.unobserved_pr_numbers == (31,)
    assert [r.correlation.run_id for r in result.runs] == ["one", "two"]
    assert [r.content_references[0].content_id for r in result.runs] == [
        "before",
        "after",
    ]
    assert result.runs[0].events == (first,)
    assert all(r.completion == "unknown" for r in result.runs)


def test_an_answer_without_findings_differs_from_no_judgement() -> None:
    result = read(
        [
            fact("pr.observed", "snapshot", {"snapshot_id": "before"}),
            fact(
                "judge.invoked",
                "judge",
                {
                    "policy_id": "ED-02",
                    "status": "judged by model",
                    "finding_count": 0,
                },
                run="two",
            ),
        ]
    )
    absent, answered = [r.policies[0] for r in result.runs]
    assert absent.judgement_event_ids == ()
    assert absent.answered is False
    assert answered.judgement_event_ids
    assert answered.answered is True
    assert absent.raised_event_ids == answered.raised_event_ids == ()


def test_costs_count_only_recorded_model_calls_and_keep_unpriced_calls() -> (
    None
):
    result = read(
        [
            fact(
                "llm.called",
                "priced",
                {
                    "call_id": "priced",
                    "policy_id": "ED-02",
                    "cost_nanodollars": 7,
                },
            ),
            fact(
                "llm.called",
                "unpriced",
                {
                    "call_id": "unpriced",
                    "policy_id": "ED-02",
                    "cost_nanodollars": None,
                    "status": "unreachable",
                },
            ),
            fact(
                "llm.called",
                "shared",
                {"call_id": "shared", "cost_nanodollars": 3},
            ),
            fact(
                "agent.dispatched",
                "collected",
                {"step": "collected", "cost": {"usd": 100}},
            ),
            fact(
                "judge.invoked",
                "judge",
                {"policy_id": "ED-02", "status": "unavailable"},
            ),
        ]
    )
    run = result.runs[0]
    assert (
        run.model_cost.nanodollars,
        run.model_cost.priced_calls,
        run.model_cost.unpriced_calls,
    ) == (10, 2, 1)
    policy = run.requested_policy_cost
    assert policy is not None
    assert (
        policy.nanodollars,
        policy.priced_calls,
        policy.unpriced_calls,
    ) == (7, 1, 1)
    assert len(policy.event_ids) == len(policy.call_ids) == 2
    assert policy.completeness == run.model_cost.completeness == "unknown"
    assert run.policies[0].judgement_statuses == ("unavailable",)


def test_observations_and_publication_flags_survive_policy_selection() -> None:
    kinds = [
        "finding.raised",
        "finding.resolved",
        "finding.rewritten",
        "finding.dismissed",
        "finding.withheld",
    ]
    observations = [
        fact(kind, "finding", {"policy_id": "ED-02"}) for kind in kinds
    ]
    observations += [
        fact(
            "action.taken",
            "observe",
            {"performed": False, "status": "observe"},
        ),
        fact(
            "judge.invoked",
            "skipped",
            {"policy_id": None, "status": "skipped: no judge configured"},
        ),
        fact("finding.raised", "other", {"policy_id": "OTHER"}),
    ]
    result = read(observations)
    assert {e.entry.event_id for e in result.runs[0].events} == {
        e.entry.event_id for e in observations
    }
    action = next(
        e.entry
        for e in result.runs[0].events
        if e.entry.event_type == "action.taken"
    )
    assert action.payload == {"performed": False, "status": "observe"}


def test_references_do_not_claim_content_exists_or_has_been_deleted() -> None:
    run = read(
        [
            fact(
                "judge.invoked",
                "judge",
                {
                    "policy_id": "ED-02",
                    "identity": {
                        "input_hash": "snapshot",
                        "exchange_id": "exchange",
                    },
                },
            ),
            fact(
                "judge.invoked",
                "missing",
                {"policy_id": "OTHER", "identity": None},
            ),
        ]
    ).runs[0]
    assert {
        (r.content_id, r.availability) for r in run.content_references
    } == {
        ("snapshot", "not_checked"),
        ("exchange", "not_checked"),
        (None, "not_recorded"),
    }


def test_an_empty_scope_returns_coverage_without_inventing_runs() -> None:
    result = read([fact("pr.observed", "other", {}, repo="other/repo")])
    assert result.runs == ()
    assert result.event_count == 0
    assert result.unobserved_pr_numbers == (30, 31)


def test_the_response_limit_includes_projection_overhead() -> None:
    response = read([])
    limit = len(response.model_dump_json().encode("utf-8")) - 1
    with pytest.raises(HistoryTooLargeError, match="response byte"):
        read([], limits=HistoryLimits(max_bytes=limit))


def test_summary_and_observations_come_from_one_read() -> None:
    class CountedHistory(InMemoryHistory):
        reads = 0

        def entries_for_history(
            self, scope: HistoryScope, limits: HistoryLimits
        ) -> tuple[StoredReviewEvent, ...]:
            self.reads += 1
            return super().entries_for_history(scope, limits)

    history = CountedHistory([fact("pr.observed", "snapshot", {})])
    result = ReadReviewHistoryUseCase(history).execute(
        ReadReviewHistoryRequest(scope=SCOPE)
    )
    assert history.reads == 1
    assert result.event_count == sum(len(run.events) for run in result.runs)


def test_a_deterministic_check_is_an_answer_without_a_judgement() -> None:
    check = fact(
        "policy.checked",
        "checked",
        {
            "policy_id": "ED-02",
            "finding_count": 0,
        },
    )
    policy = read([check]).runs[0].policies[0]
    assert policy.answered is True
    assert policy.checked_event_ids == (str(check.entry.event_id),)
    assert policy.judgement_event_ids == ()
    assert policy.raised_event_ids == ()
    assert (
        policy.model_cost.priced_calls == policy.model_cost.unpriced_calls == 0
    )
