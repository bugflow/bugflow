"""Tests of the activity that reads a closed pull request's
conversation: the review context's use case over a forge's
conversation, carried across by the worker's adapter."""

from datetime import UTC, datetime

import pytest
from temporalio.exceptions import ApplicationError

from bugflow.apps.worker.activities import ReviewActivities
from bugflow.apps.worker.tests.activities import (
    REF,
    FakeDoctrine,
    FixedClock,
)
from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.domain.values.conversation import PullRequestState, Reaction
from bugflow.forge.infrastructure.in_memory_snapshots import (
    InMemorySnapshotStore,
)
from bugflow.review.domain.facts import ACTION_TAKEN
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.dtos.collect_at_close import CollectAtCloseRequest
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.tests.journal import QueryableJournal
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

AT = datetime(2030, 3, 12, tzinfo=UTC)
CLOSING = Correlation(
    workflow_id="pr/github/example-org/widgets/1", run_id="w"
)


class NoForge:
    """The evaluation's forge, which collecting at close never asks."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"the evaluation's forge was asked for {name}")


class Conversing:
    def __init__(self, error: Exception | None = None) -> None:
        self._error = error

    def reactions(
        self, ref: PullRequestRef, comment_id: int
    ) -> tuple[Reaction, ...]:
        if self._error:
            raise self._error
        return (Reaction(content="+1", login="a-reader", reacted_at=AT),)

    def state(self, ref: PullRequestRef) -> PullRequestState:
        return PullRequestState(merged=True, head_sha="c" * 40)


def activities(
    journal: QueryableJournal, conversation: Conversing | None
) -> ReviewActivities:
    return ReviewActivities(
        forge=NoForge(),  # type: ignore[arg-type]
        doctrine=FakeDoctrine(),
        judge=None,
        journal=journal,
        snapshots=InMemorySnapshotStore(),
        clock=FixedClock(),
        archive=InMemoryJudgeArchive(),
        conversation=conversation,
    )


def posted(journal: QueryableJournal) -> None:
    """Record that an evaluation posted a comment on the pull request."""
    evaluation = Correlation(
        workflow_id=f"{CLOSING.workflow_id}/evaluation/d", run_id="e"
    )
    journal.append(
        [
            Recorder(REF, evaluation, "v1", AT).entry(
                ACTION_TAKEN,
                "review_comment/prose",
                {
                    "action": "review_comment",
                    "agent_id": "prose",
                    "performed": True,
                    "comment_id": 41,
                },
            )
        ]
    )


def test_the_activity_records_what_the_forge_says_of_the_conversation() -> (
    None
):
    journal = QueryableJournal()
    posted(journal)

    response = activities(journal, Conversing()).collect_at_close(
        CollectAtCloseRequest(ref=REF, correlation=CLOSING)
    )

    assert (response.reactions, response.merged) == (1, True)
    (reaction,) = [
        e for e in journal.entries if e.event_type == "reaction.recorded"
    ]
    assert (reaction.payload["login"], reaction.payload["content"]) == (
        "a-reader",
        "+1",
    )


def test_a_forge_that_refuses_fails_the_activity_for_good() -> None:
    journal = QueryableJournal()
    posted(journal)
    refusing = activities(journal, Conversing(ForgeRejectedError("403")))

    with pytest.raises(ApplicationError) as raised:
        refusing.collect_at_close(
            CollectAtCloseRequest(ref=REF, correlation=CLOSING)
        )

    assert raised.value.non_retryable


def test_no_forge_that_reads_a_conversation_fails_it_for_good_too() -> None:
    built = activities(QueryableJournal(), None)

    with pytest.raises(ApplicationError) as raised:
        built.collect_at_close(
            CollectAtCloseRequest(ref=REF, correlation=CLOSING)
        )

    assert raised.value.non_retryable
    assert built.collecting.startswith("not collecting at close")
