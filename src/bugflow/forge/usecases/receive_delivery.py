"""Use case: receive one delivery from a forge and act on it.

A forge may send the same delivery more than once. Each delivery is acted
on once: its id is recorded, and a delivery whose id is already recorded is
answered as a duplicate.

The order of the two steps matters. The evaluation is started first and the
delivery recorded second. If starting fails, nothing has been recorded, so
when the forge sends the delivery again it is tried again and not dropped
as a duplicate.
"""

from dataclasses import asdict
from datetime import datetime

from bugflow.forge.domain import facts
from bugflow.forge.domain.models.delivery import Delivery
from bugflow.forge.domain.models.polling import POLLED_DELIVERY_PREFIX
from bugflow.forge.domain.services.corpus_refresh import CorpusRefreshPort
from bugflow.forge.domain.services.evaluations import EvaluationStarterPort
from bugflow.forge.domain.services.journal_history import (
    DeliveryJournalService,
)
from bugflow.forge.dtos.receive_delivery import (
    Outcome,
    ReceiveDeliveryRequest,
    ReceiveDeliveryResponse,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.dismissal import parse_dismissal

# The pull request actions after which a review could come out differently.
EVALUATED_ACTIONS = frozenset(
    {"opened", "synchronize", "reopened", "edited", "ready_for_review"}
)


def _route(delivery: Delivery) -> tuple[Outcome, str]:
    if delivery.event == "issue_comment":
        dismissal = (
            parse_dismissal(delivery.comment.body)
            if delivery.comment is not None and delivery.action == "created"
            else None
        )
        if dismissal is None or delivery.ref is None:
            return "ignored", "issue_comment is not a dismissal"
        return "dismiss", f"dismissal of {dismissal.policy_id}"
    if delivery.event != "pull_request" or delivery.ref is None:
        return "ignored", f"{delivery.event} is not evaluated"
    if delivery.action == "closed":
        return "close", "pull_request closed"
    if delivery.action not in EVALUATED_ACTIONS:
        return "ignored", f"pull_request {delivery.action} is not evaluated"
    return "evaluate", f"pull_request {delivery.action}"


def dismissal_entries(
    delivery: Delivery,
    outcome: Outcome,
    correlation: Correlation,
    occurred_at: datetime,
) -> list[JournalEntry]:
    """The journal entry for a ``/dismiss`` comment."""
    if (
        outcome != "dismiss"
        or delivery.comment is None
        or delivery.ref is None
    ):
        return []
    dismissal = parse_dismissal(delivery.comment.body)
    if dismissal is None:
        return []
    ref = delivery.ref
    return [
        JournalEntry(
            event_id=event_id(
                correlation, facts.FINDING_DISMISSED, delivery.delivery_id
            ),
            occurred_at=occurred_at,
            event_type=facts.FINDING_DISMISSED,
            forge=delivery.forge,
            repo=f"{ref.owner}/{ref.repo}",
            pr_number=ref.number,
            commit_sha=None,
            corpus_version=None,
            workflow_id=correlation.workflow_id,
            run_id=correlation.run_id,
            payload={
                **asdict(dismissal),
                "actor": delivery.comment.author,
                "comment_id": delivery.comment.comment_id,
                "delivery_id": delivery.delivery_id,
            },
        )
    ]


def merge_entries(
    delivery: Delivery,
    outcome: Outcome,
    correlation: Correlation,
    occurred_at: datetime,
) -> list[JournalEntry]:
    """The journal entry for a pull request being merged.

    A merge is recorded as a fact of its own so that it can be counted
    later: for example, how often a pull request was merged although a
    review had raised a concern.
    """
    if outcome != "close" or not delivery.merged or delivery.ref is None:
        return []
    ref = delivery.ref
    return [
        JournalEntry(
            event_id=event_id(
                correlation, facts.PR_MERGED, delivery.delivery_id
            ),
            occurred_at=occurred_at,
            event_type=facts.PR_MERGED,
            forge=delivery.forge,
            repo=f"{ref.owner}/{ref.repo}",
            pr_number=ref.number,
            commit_sha=delivery.merge_commit_sha,
            corpus_version=None,
            workflow_id=correlation.workflow_id,
            run_id=correlation.run_id,
            payload={"delivery_id": delivery.delivery_id},
        )
    ]


def _polled(delivery: Delivery) -> bool:
    return delivery.delivery_id.startswith(POLLED_DELIVERY_PREFIX)


class ReceiveDeliveryUseCase:
    """Takes one delivery. Returns what it led to: "evaluate", "close",
    "dismiss", "duplicate" or "ignored".

    When a delivery reports a merge and a ``corpora`` service was given,
    that service is asked to load the repository's corpus again.
    """

    def __init__(
        self,
        journal: DeliveryJournalService,
        clock: ClockService,
        evaluations: EvaluationStarterPort,
        corpora: CorpusRefreshPort | None = None,
    ) -> None:
        self._journal = journal
        self._clock = clock
        self._evaluations = evaluations
        self._corpora = corpora

    def execute(
        self, request: ReceiveDeliveryRequest
    ) -> ReceiveDeliveryResponse:
        delivery = request.delivery
        fact_id = facts.delivery_id(delivery.forge, delivery.delivery_id)
        if self._journal.has_event(fact_id):
            return ReceiveDeliveryResponse(
                outcome="duplicate",
                reason=f"delivery {delivery.delivery_id} already received",
                ref=delivery.ref,
            )

        outcome, reason = _route(delivery)
        if outcome in ("evaluate", "close") and self._covered(delivery):
            outcome = "ignored"
            reason = "polled, and delivered already since its last update"
        evaluation = None
        if outcome in ("evaluate", "dismiss") and delivery.ref is not None:
            evaluation = self._evaluations.start(
                delivery.ref, delivery.delivery_id
            )
        elif outcome == "close" and delivery.ref is not None:
            evaluation = self._evaluations.close(
                delivery.ref, delivery.delivery_id, merged=delivery.merged
            )
            if delivery.merged and self._corpora is not None:
                ref = delivery.ref
                self._corpora.refresh(
                    delivery.forge, f"{ref.owner}/{ref.repo}"
                )
        # A delivery that was not passed to a workflow is recorded under a run
        # named after the delivery itself.
        correlation = evaluation or Correlation(
            workflow_id=f"delivery/{delivery.forge}",
            run_id=delivery.delivery_id,
        )

        self._journal.append(
            [
                JournalEntry(
                    event_id=fact_id,
                    occurred_at=self._clock.now(),
                    event_type=facts.DELIVERY_RECEIVED,
                    forge=delivery.forge,
                    repo=delivery.repository or "unknown",
                    pr_number=delivery.ref.number if delivery.ref else None,
                    commit_sha=None,
                    corpus_version=None,
                    workflow_id=correlation.workflow_id,
                    run_id=correlation.run_id,
                    payload={
                        "delivery_id": delivery.delivery_id,
                        "event": delivery.event,
                        "action": delivery.action,
                        "outcome": outcome,
                        "reason": reason,
                    },
                ),
                *dismissal_entries(
                    delivery, outcome, correlation, self._clock.now()
                ),
                *merge_entries(
                    delivery, outcome, correlation, self._clock.now()
                ),
            ]
        )
        return ReceiveDeliveryResponse(
            outcome=outcome,
            reason=reason,
            ref=delivery.ref,
            evaluation=evaluation,
        )

    def _covered(self, delivery: Delivery) -> bool:
        """Whether a polled delivery reports something a webhook has already
        reported.

        The poller exists to catch deliveries that were lost. It cannot
        know what the webhook delivered, so most of what it sends repeats
        the webhook. If a delivery for the pull request was received after
        the pull request last changed, nothing was lost, and the polled one
        is ignored.

        This applies only to polled deliveries. A webhook delivery is the
        forge reporting something now, and is always acted on.
        """
        return (
            _polled(delivery)
            and delivery.ref is not None
            and delivery.updated_at is not None
            and self._journal.received_since(delivery.ref, delivery.updated_at)
        )
