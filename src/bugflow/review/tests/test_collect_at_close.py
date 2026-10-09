"""Tests of ``CollectAtCloseUseCase``: what is recorded when a pull
request closes."""

from datetime import UTC, datetime

from bugflow.review.domain.models.conversation import Closing, Reaction
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.dtos.collect_at_close import CollectAtCloseRequest
from bugflow.review.tests.journal import QueryableJournal
from bugflow.review.usecases.collect_at_close import CollectAtCloseUseCase
from bugflow.shared.domain.models.journal_entry import JournalEntry
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

REF = PullRequestRef(owner="orchard", repo="pear-tree", number=7)
EVALUATION = Correlation(workflow_id="pr/7/evaluation/d-1", run_id="e1")
CLOSING = Correlation(workflow_id="pr/7", run_id="w1")
AT = datetime(2030, 9, 22, 5, tzinfo=UTC)
FINDING = Finding(
    policy_id="P-01",
    severity="warn",
    clause="RULE-6",
    subject='description "seamless"',
    message="Praise.",
)


class FixedClock:
    def now(self) -> datetime:
        return AT


class Conversation:
    def __init__(
        self,
        reactions: dict[int, tuple[Reaction, ...]] | None = None,
        merged: bool = True,
    ) -> None:
        self._reactions = reactions or {}
        self._merged = merged
        self.asked: list[int] = []

    def reactions(
        self, ref: PullRequestRef, comment_id: int
    ) -> tuple[Reaction, ...]:
        self.asked.append(comment_id)
        return self._reactions.get(comment_id, ())

    def state(self, ref: PullRequestRef) -> Closing:
        return Closing(merged=self._merged, head_sha="c" * 40)


def published(
    agent_id: str, comment_id: int | None, performed: bool = True
) -> JournalEntry:
    return Recorder(REF, EVALUATION, "v1", AT).entry(
        "action.taken",
        f"review_comment/{agent_id}",
        {
            "action": "review_comment",
            "agent_id": agent_id,
            "performed": performed,
            "comment_id": comment_id,
        },
    )


def journal_with(*entries: JournalEntry) -> QueryableJournal:
    journal = QueryableJournal()
    journal.append(list(entries))
    return journal


def collect(journal: QueryableJournal, conversation: Conversation) -> None:
    CollectAtCloseUseCase(journal, conversation, FixedClock()).execute(
        CollectAtCloseRequest(ref=REF, correlation=CLOSING)
    )


def recorded(journal: QueryableJournal, event_type: str) -> list[JournalEntry]:
    return [e for e in journal.entries if e.event_type == event_type]


def test_each_reaction_on_a_posted_comment_is_recorded() -> None:
    journal = journal_with(published("prose", 41), published("safety", 42))
    conversation = Conversation(
        {
            41: (Reaction(content="-1", login="chris", reacted_at=AT),),
            42: (
                Reaction(content="+1", login="chris"),
                Reaction(content="eyes", login="sam"),
            ),
        }
    )

    collect(journal, conversation)

    reactions = recorded(journal, "reaction.recorded")
    assert sorted(
        (r.payload["comment_id"], r.payload["agent_id"], r.payload["content"])
        for r in reactions
    ) == [
        (41, "prose", "-1"),
        (42, "safety", "+1"),
        (42, "safety", "eyes"),
    ]
    assert {r.payload["evaluated_in"] for r in reactions} == {"e1"}
    assert {r.payload["login"] for r in reactions} == {"chris", "sam"}


def test_a_comment_that_was_never_posted_is_not_asked_about() -> None:
    journal = journal_with(
        published("prose", None, performed=False),
        published("safety", 42, performed=False),
    )
    conversation = Conversation()

    collect(journal, conversation)

    assert conversation.asked == []


def test_the_close_records_whether_it_merged() -> None:
    for merged in (True, False):
        journal = journal_with(published("prose", 41))

        collect(journal, Conversation(merged=merged))

        (closed,) = recorded(journal, "pr.closed")
        assert closed.payload["merged"] is merged
        assert closed.commit_sha == "c" * 40


def test_the_close_names_what_the_last_evaluation_left_outstanding() -> None:
    raised = Recorder(REF, EVALUATION, "v1", AT).findings("judge", [FINDING])
    journal = journal_with(published("prose", 41), *raised)

    collect(journal, Conversation())

    (closed,) = recorded(journal, "pr.closed")
    assert closed.payload["outstanding"] == [
        {
            "policy_id": "P-01",
            "clause": "RULE-6",
            "subject": 'description "seamless"',
        }
    ]


def test_collecting_twice_records_nothing_twice() -> None:
    journal = journal_with(published("prose", 41))
    conversation = Conversation({41: (Reaction(content="+1", login="chris"),)})

    collect(journal, conversation)
    collect(journal, conversation)

    assert len(recorded(journal, "reaction.recorded")) == 1
    assert len(recorded(journal, "pr.closed")) == 1


def test_a_reaction_names_every_reviewer_the_comment_carried() -> None:
    journal = journal_with(published("prose", 7), published("safety", 7))
    collect(
        journal,
        Conversation({7: (Reaction(content="+1", login="sam"),)}),
    )
    (reaction,) = recorded(journal, "reaction.recorded")
    assert reaction.payload["agents"] == ["prose", "safety"]
    assert reaction.payload["agent_id"] is None
