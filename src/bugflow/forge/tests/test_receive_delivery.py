"""Tests of receiving a delivery: each one is acted on once, and what is done
depends on the kind of event.
"""

from datetime import UTC, datetime, timedelta

import pytest

from bugflow.forge.domain.errors import EvaluationStartError
from bugflow.forge.domain.models.delivery import Delivery, DeliveryComment
from bugflow.forge.dtos.receive_delivery import (
    ReceiveDeliveryRequest,
    ReceiveDeliveryResponse,
)
from bugflow.forge.tests.journal import QueryableJournal
from bugflow.forge.usecases.receive_delivery import ReceiveDeliveryUseCase
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="o", repo="r", number=6)
STARTED = Correlation(workflow_id="pr/github/o/r/6", run_id="run-1")


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 9, 11, tzinfo=UTC)


class FakeEvaluations:
    def __init__(self, fail: bool = False, running: bool = True) -> None:
        self.started: list[tuple[PullRequestRef, str]] = []
        self.closed: list[tuple[PullRequestRef, str]] = []
        self.merged: list[bool] = []
        self.fail = fail
        self.running = running

    def start(self, ref: PullRequestRef, delivery_id: str) -> Correlation:
        if self.fail:
            raise EvaluationStartError("Temporal is unreachable")
        self.started.append((ref, delivery_id))
        return STARTED

    def close(
        self, ref: PullRequestRef, delivery_id: str, merged: bool = False
    ) -> Correlation | None:
        self.closed.append((ref, delivery_id))
        self.merged.append(merged)
        return STARTED if self.running else None


def delivery(
    delivery_id: str = "d-1",
    event: str = "pull_request",
    action: str | None = "opened",
    ref: PullRequestRef | None = REF,
    merged: bool = False,
    merge_commit_sha: str | None = None,
    updated_at: datetime | None = None,
) -> Delivery:
    return Delivery(
        forge="github",
        delivery_id=delivery_id,
        event=event,
        action=action,
        repository="o/r",
        ref=ref,
        merged=merged,
        merge_commit_sha=merge_commit_sha,
        updated_at=updated_at,
    )


class FakeCorpora:
    def __init__(self) -> None:
        self.refreshed: list[tuple[str, str]] = []

    def refresh(self, forge: str, repository: str) -> Correlation:
        self.refreshed.append((forge, repository))
        return STARTED


def receive(
    journal: QueryableJournal,
    evaluations: FakeEvaluations,
    item: Delivery,
    corpora: FakeCorpora | None = None,
) -> ReceiveDeliveryResponse:
    return ReceiveDeliveryUseCase(
        journal, FixedClock(), evaluations, corpora
    ).execute(ReceiveDeliveryRequest(delivery=item))


def test_an_opened_pull_request_starts_an_evaluation() -> None:
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    response = receive(journal, evaluations, delivery())
    assert response.outcome == "evaluate"
    assert response.evaluation == STARTED
    assert evaluations.started == [(REF, "d-1")]


def test_the_delivery_is_recorded_on_the_evaluation_it_started() -> None:
    journal = QueryableJournal()
    receive(journal, FakeEvaluations(), delivery())
    (entry,) = journal.entries
    assert entry.event_type == "delivery.received"
    assert (entry.workflow_id, entry.run_id) == ("pr/github/o/r/6", "run-1")
    assert entry.payload["outcome"] == "evaluate"


def test_when_the_evaluation_cannot_start_nothing_is_recorded() -> None:
    journal = QueryableJournal()
    with pytest.raises(EvaluationStartError):
        receive(journal, FakeEvaluations(fail=True), delivery())
    assert journal.entries == []
    # Because nothing was recorded, the same delivery sent again is acted on
    # and not dropped as a duplicate.
    assert (
        receive(journal, FakeEvaluations(), delivery()).outcome == "evaluate"
    )


def test_a_redelivery_is_a_duplicate_and_starts_nothing() -> None:
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    receive(journal, evaluations, delivery())
    assert receive(journal, evaluations, delivery()).outcome == "duplicate"
    assert len(evaluations.started) == 1
    assert len(journal.entries) == 1


def test_actions_that_do_not_change_the_evaluation_are_ignored() -> None:
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    response = receive(journal, evaluations, delivery(action="labeled"))
    assert response.outcome == "ignored"
    assert evaluations.started == []
    (entry,) = journal.entries
    assert (entry.workflow_id, entry.run_id) == ("delivery/github", "d-1")


def test_events_other_than_pull_requests_are_ignored() -> None:
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    push = delivery(event="push", action=None, ref=None)
    assert receive(journal, evaluations, push).outcome == "ignored"
    assert journal.entries[0].pr_number is None


def test_a_closed_pull_request_closes_its_workflow() -> None:
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    response = receive(journal, evaluations, delivery(action="closed"))
    assert response.outcome == "close"
    assert evaluations.closed == [(REF, "d-1")]
    assert evaluations.started == []
    (entry,) = journal.entries
    assert (entry.workflow_id, entry.run_id) == ("pr/github/o/r/6", "run-1")


def test_a_merge_is_recorded_as_a_fact_of_its_own() -> None:
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    receive(
        journal,
        evaluations,
        delivery(action="closed", merged=True, merge_commit_sha="abc123"),
    )
    merged = [e for e in journal.entries if e.event_type == "pr.merged"]
    assert [(e.repo, e.pr_number, e.commit_sha) for e in merged] == [
        ("o/r", 6, "abc123")
    ]


def test_a_pull_request_closed_unmerged_records_no_merge() -> None:
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    receive(journal, evaluations, delivery(action="closed"))
    assert [e.event_type for e in journal.entries] == ["delivery.received"]


def test_closing_with_no_workflow_running_is_recorded_against_itself() -> None:
    journal = QueryableJournal()
    receive(journal, FakeEvaluations(running=False), delivery(action="closed"))
    (entry,) = journal.entries
    assert (entry.workflow_id, entry.run_id) == ("delivery/github", "d-1")


def comment(
    body: str,
    delivery_id: str = "c-1",
    action: str = "created",
    ref: PullRequestRef | None = REF,
) -> Delivery:
    return Delivery(
        forge="github",
        delivery_id=delivery_id,
        event="issue_comment",
        action=action,
        repository="o/r",
        ref=ref,
        comment=DeliveryComment(comment_id=99, author="reviewer", body=body),
    )


def dismissals(journal: QueryableJournal) -> list[dict[str, object]]:
    return [
        e.payload
        for e in journal.entries
        if e.event_type == "finding.dismissed"
    ]


def test_a_dismissal_is_recorded_as_a_fact_and_starts_an_evaluation() -> None:
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    response = receive(
        journal, evaluations, comment("/dismiss ED-01 evidence, not narration")
    )
    assert response.outcome == "dismiss"
    assert evaluations.started == [(REF, "c-1")]
    (fact,) = dismissals(journal)
    assert fact["policy_id"] == "ED-01"
    assert fact["reason"] == "evidence, not narration"
    assert (fact["actor"], fact["comment_id"]) == ("reviewer", 99)


def test_a_redelivered_dismissal_is_recorded_once() -> None:
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    item = comment("/dismiss ED-01 evidence, not narration")
    receive(journal, evaluations, item)
    assert receive(journal, evaluations, item).outcome == "duplicate"
    assert len(dismissals(journal)) == 1


@pytest.mark.parametrize(
    ("body", "action", "ref"),
    [
        ("Thanks!", "created", REF),
        ("/dismiss ED-01 a reason", "edited", REF),
        ("/dismiss ED-01 a reason", "created", None),
    ],
    ids=["not a command", "edited", "not a pull request"],
)
def test_other_comments_are_ignored(
    body: str, action: str, ref: PullRequestRef | None
) -> None:
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    response = receive(
        journal, evaluations, comment(body, action=action, ref=ref)
    )
    assert response.outcome == "ignored"
    assert evaluations.started == []
    assert dismissals(journal) == []


def test_the_workflow_is_told_whether_the_close_merged() -> None:
    """When a pull request closes, its workflow is told whether it was merged.
    A merged pull request gets a final review and an abandoned one does
    not.
    """
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    receive(
        journal,
        evaluations,
        delivery("d-merged", action="closed", merged=True),
    )
    receive(journal, evaluations, delivery("d-abandoned", action="closed"))
    assert evaluations.merged == [True, False]


def test_a_merge_refreshes_the_repository_s_corpus() -> None:
    """A merge can change the documents a repository keeps, so after a merge
    the repository's corpus is asked to be loaded again.
    """
    journal, corpora = QueryableJournal(), FakeCorpora()
    receive(
        journal,
        FakeEvaluations(),
        delivery("d-merged", action="closed", merged=True),
        corpora,
    )
    assert corpora.refreshed == [("github", "o/r")]


def test_an_abandoned_pull_request_refreshes_nothing() -> None:
    corpora = FakeCorpora()
    receive(
        QueryableJournal(),
        FakeEvaluations(),
        delivery("d-abandoned", action="closed"),
        corpora,
    )
    receive(QueryableJournal(), FakeEvaluations(), delivery(), corpora)
    assert corpora.refreshed == []


# The time the fixed clock gives, which is when the journal records a delivery
# as received.
RECEIVED = FixedClock().now()


def test_a_poll_of_a_state_the_webhook_already_delivered_is_ignored() -> None:
    """A polled delivery is ignored when a delivery for the same pull request
    was received after the pull request last changed. Nothing was lost, so
    there is nothing for the poll to make up for.
    """
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    receive(journal, evaluations, delivery("webhook-1", action="synchronize"))

    polled = receive(
        journal,
        evaluations,
        delivery(
            "poll-0123",
            action="synchronize",
            updated_at=RECEIVED - timedelta(minutes=1),
        ),
    )

    assert polled.outcome == "ignored"
    assert evaluations.started == [(REF, "webhook-1")]


def test_a_poll_of_a_state_no_webhook_delivered_is_evaluated() -> None:
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    receive(journal, evaluations, delivery("webhook-1", action="synchronize"))

    polled = receive(
        journal,
        evaluations,
        delivery(
            "poll-0123",
            action="synchronize",
            updated_at=RECEIVED + timedelta(minutes=1),
        ),
    )

    assert polled.outcome == "evaluate"


def test_a_poll_that_does_not_say_when_is_evaluated_as_before() -> None:
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    receive(journal, evaluations, delivery("webhook-1", action="synchronize"))

    polled = receive(
        journal, evaluations, delivery("poll-0123", action="synchronize")
    )

    assert polled.outcome == "evaluate"


def test_a_webhook_is_never_taken_for_a_stale_poll() -> None:
    """That rule applies only to polled deliveries. A webhook delivery is
    always acted on, whatever the times say.
    """
    journal, evaluations = QueryableJournal(), FakeEvaluations()
    receive(journal, evaluations, delivery("webhook-1", action="synchronize"))

    again = receive(
        journal,
        evaluations,
        delivery(
            "webhook-2",
            action="synchronize",
            updated_at=RECEIVED - timedelta(minutes=1),
        ),
    )

    assert again.outcome == "evaluate"
