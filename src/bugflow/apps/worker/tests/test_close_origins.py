"""Closing records retain the source and reuse only its review evidence."""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import httpx2
import pytest

from bugflow.apps.shared.journals import review_journal
from bugflow.apps.worker.conversation import ForgeConversation
from bugflow.forge.infrastructure.github import GitHubForge
from bugflow.review.domain.models.conversation import Closing, Reaction
from bugflow.review.domain.models.recorder import Recorder
from bugflow.review.dtos.collect_at_close import CollectAtCloseRequest
from bugflow.review.tests.journal import QueryableJournal
from bugflow.review.tests.test_collect_at_close import (
    AT,
    CLOSING,
    FINDING,
    REF,
    Conversation,
    FixedClock,
)
from bugflow.review.usecases.collect_at_close import CollectAtCloseUseCase
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.repository_association import (
    AssociationConflictError,
    RepositoryAssociationUnresolvedError,
)

ORIGIN = "github.com/orchard/pear-tree"


@pytest.fixture(params=["memory", "postgres"])
def journal(request: pytest.FixtureRequest) -> Any:
    if request.param == "memory":
        return QueryableJournal()
    return review_journal(request.getfixturevalue("database_url"), None)


def seed(journal: Any, origin: str | None, name: str, hours: int = 0) -> None:
    recorder = Recorder(
        REF,
        Correlation(workflow_id="evaluation", run_id=name),
        "v1",
        AT + timedelta(hours=hours),
        origin=origin,
    )
    journal.append(
        [
            recorder.entry(
                "action.taken",
                "posted",
                {
                    "action": "review_comment",
                    "performed": True,
                    "comment_id": 41,
                    "agent_id": name,
                },
            ),
            *recorder.findings("judge", [replace(FINDING, subject=name)]),
        ]
    )


def test_close_uses_only_same_origin_history_and_associates_every_fact(
    journal: Any,
) -> None:
    seed(journal, ORIGIN, "same")
    seed(journal, "other.test/orchard/pear-tree", "foreign", 1)
    seed(journal, None, "unresolved", 2)
    seen: list[str] = []

    def serve(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/reactions"):
            return httpx2.Response(
                200, json=[{"content": "+1", "user": {"login": "member"}}]
            )
        return httpx2.Response(
            200,
            json={
                "merged": True,
                "head": {"sha": "sha"},
                "html_url": "https://untrusted.test/orchard/pear-tree",
            },
        )

    conversation = ForgeConversation(
        GitHubForge("token", transport=httpx2.MockTransport(serve))
    )
    use_case = CollectAtCloseUseCase(journal, conversation, FixedClock())
    request = CollectAtCloseRequest(ref=REF, correlation=CLOSING)
    result = use_case.execute(request)
    assert result.reactions == result.outstanding == 1
    entries = journal.entries_for_run(CLOSING)
    assert len(entries) == 2
    assert {entry.origin for entry in entries} == {ORIGIN}
    reaction = next(e for e in entries if e.event_type == "reaction.recorded")
    assert reaction.payload["agents"] == ["same"]
    assert reaction.payload["evaluated_in"] == "same"
    closed = next(e for e in entries if e.event_type == "pr.closed")
    assert closed.payload["outstanding"][0]["subject"] == "same"
    assert seen == [
        "/repos/orchard/pear-tree/pulls/7",
        "/repos/orchard/pear-tree/issues/comments/41/reactions",
    ]
    expected = Recorder(REF, CLOSING, None, AT).entry(
        "pr.closed", "closed", {}
    )
    assert closed.event_id == expected.event_id
    assert use_case.execute(request) == result
    assert journal.entries_for_run(CLOSING) == entries


class SourcedConversation(Conversation):
    def __init__(self, origin: str | None) -> None:
        super().__init__({41: (Reaction(content="+1", login="member"),)})
        self.origin = origin

    def state(self, ref: Any) -> Closing:
        return Closing(merged=True, origin=self.origin)


@pytest.mark.parametrize(
    "held_origin, observed_origin, error",
    [
        (None, ORIGIN, RepositoryAssociationUnresolvedError),
        ("other.test/orchard/pear-tree", ORIGIN, AssociationConflictError),
        (ORIGIN, None, AssociationConflictError),
    ],
)
def test_close_refuses_conflicting_or_unresolved_run_before_reading_reactions(
    journal: Any,
    held_origin: str | None,
    observed_origin: str | None,
    error: type[Exception],
) -> None:
    seed(journal, ORIGIN, "same")
    held = Recorder(REF, CLOSING, None, AT, origin=held_origin).entry(
        "delivery.received", "delivery", {}
    )
    journal.append([held])
    before = journal.entries_for_run(CLOSING)
    conversation = SourcedConversation(observed_origin)
    with pytest.raises(error):
        CollectAtCloseUseCase(journal, conversation, FixedClock()).execute(
            CollectAtCloseRequest(ref=REF, correlation=CLOSING)
        )
    assert conversation.asked == []
    assert journal.entries_for_run(CLOSING) == before


def test_unresolved_close_cannot_be_reassociated_on_retry(
    journal: Any,
) -> None:
    request = CollectAtCloseRequest(ref=REF, correlation=CLOSING)
    CollectAtCloseUseCase(
        journal, SourcedConversation(None), FixedClock()
    ).execute(request)
    before = journal.entries_for_run(CLOSING)
    with pytest.raises(RepositoryAssociationUnresolvedError):
        CollectAtCloseUseCase(
            journal, SourcedConversation(ORIGIN), FixedClock()
        ).execute(request)
    assert journal.entries_for_run(CLOSING) == before
    assert before[0].origin is None


def test_different_repository_origin_is_refused_before_historical_reads(
    journal: Any,
) -> None:
    conversation = SourcedConversation("github.com/other/repository")
    with pytest.raises(ValueError, match="does not match"):
        CollectAtCloseUseCase(journal, conversation, FixedClock()).execute(
            CollectAtCloseRequest(ref=REF, correlation=CLOSING)
        )
    assert not conversation.asked
    assert not journal.entries_for_run(CLOSING)
