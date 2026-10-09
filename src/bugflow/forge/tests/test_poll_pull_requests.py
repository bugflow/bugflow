"""Tests of polling.

The use case runs with a fake feed of changes and a fake server to post to.
Most tests are about the delivery id, because the id is what makes polling
the same thing twice harmless: they check when it stays the same and when
it changes.
"""

from datetime import UTC, datetime, timedelta

import pytest

from bugflow.forge.domain.errors import (
    DeliveryNotAcceptedError,
    ForgeUnavailableError,
)
from bugflow.forge.domain.models.delivery import Delivery, DeliveryComment
from bugflow.forge.domain.models.polling import (
    PolledComment,
    PolledPullRequest,
)
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.dtos.poll_pull_requests import PollPullRequestsRequest
from bugflow.forge.usecases.poll_pull_requests import (
    COMMENT_LOOKBACK,
    OVERLAP,
    PollPullRequestsUseCase,
    delivery_for,
    delivery_for_comment,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.serde import from_json

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=UTC)


class FixedClock:
    def now(self) -> datetime:
        return NOW


class FakeFeed:
    def __init__(
        self,
        pulls: dict[str, list[PolledPullRequest] | Exception],
        comments: dict[str, list[PolledComment]] | None = None,
    ) -> None:
        self.pulls = pulls
        self.comments = comments or {}
        self.asked: list[tuple[str, datetime | None]] = []
        self.asked_comments: list[tuple[str, datetime]] = []

    def updated_pull_requests(
        self, owner: str, repo: str, since: datetime | None
    ) -> list[PolledPullRequest]:
        self.asked.append((f"{owner}/{repo}", since))
        found = self.pulls[f"{owner}/{repo}"]
        if isinstance(found, Exception):
            raise found
        return found

    def updated_comments(
        self, owner: str, repo: str, since: datetime
    ) -> list[PolledComment]:
        self.asked_comments.append((f"{owner}/{repo}", since))
        return self.comments.get(f"{owner}/{repo}", [])


class FakeIngress:
    def __init__(self, refuse: frozenset[int] = frozenset()) -> None:
        self.refuse = refuse
        self.received: list[Delivery] = []

    def send(self, delivery: Delivery) -> str:
        assert delivery.ref is not None
        if delivery.ref.number in self.refuse:
            raise DeliveryNotAcceptedError("the ingress answered 503")
        self.received.append(delivery)
        return "evaluate"


def pull(number: int = 7, **changes: object) -> PolledPullRequest:
    fields: dict[str, object] = {
        "ref": PullRequestRef(owner="o", repo="r", number=number),
        "open": True,
        "head_sha": "a" * 40,
        "title": "Add the poller",
        "body": "Why.",
        "updated_at": NOW - timedelta(minutes=1),
    }
    return from_json(PolledPullRequest, fields | changes)


def poll(feed: FakeFeed, ingress: FakeIngress, since: datetime | None = None):  # type: ignore[no-untyped-def]
    use_case = PollPullRequestsUseCase({"github": feed}, ingress, FixedClock())
    return use_case.execute(
        PollPullRequestsRequest(repositories=tuple(feed.pulls), since=since)
    )


def test_an_open_pull_request_is_posted_as_a_synchronize_delivery() -> None:
    delivery = delivery_for(pull())
    assert delivery.event == "pull_request"
    assert delivery.action == "synchronize"
    assert delivery.repository == "o/r"
    assert delivery.ref == PullRequestRef(owner="o", repo="r", number=7)
    assert delivery.delivery_id.startswith("poll-")


def test_a_polled_delivery_says_when_the_pull_request_was_last_updated() -> (
    None
):
    """A polled delivery carries the time the pull request last changed, so
    the server can tell whether a webhook has already reported that change.
    """
    assert delivery_for(pull()).updated_at == NOW - timedelta(minutes=1)


def test_a_closed_pull_request_is_posted_as_closed() -> None:
    closed = pull(open=False, closed_at=NOW)
    assert delivery_for(closed).action == "closed"


def test_an_unchanged_pull_request_keeps_its_delivery_id() -> None:
    later = pull(updated_at=NOW, body="Why.")
    assert delivery_for(pull()).delivery_id == delivery_for(later).delivery_id


def test_what_an_evaluation_sees_changes_the_delivery_id() -> None:
    before = delivery_for(pull()).delivery_id
    for changed in (
        pull(head_sha="b" * 40),
        pull(title="Add the poller service"),
        pull(body="Why, at length."),
        pull(open=False, closed_at=NOW),
        pull(number=8),
    ):
        assert delivery_for(changed).delivery_id != before


def test_changes_are_posted_oldest_first() -> None:
    feed = FakeFeed({"o/r": [pull(9), pull(8), pull(7)]})
    ingress = FakeIngress()
    response = poll(feed, ingress)
    assert [d.ref.number for d in ingress.received if d.ref] == [7, 8, 9]
    assert [s.outcome for s in response.sent] == ["evaluate"] * 3


def test_the_window_moves_on_once_every_delivery_is_accepted() -> None:
    since = NOW - timedelta(hours=1)
    response = poll(FakeFeed({"o/r": [pull()]}), FakeIngress(), since)
    assert response.next_since == NOW - OVERLAP
    assert response.failures == ()


def test_a_refused_delivery_keeps_the_window_for_the_next_poll() -> None:
    since = NOW - timedelta(hours=1)
    ingress = FakeIngress(refuse=frozenset({8}))
    response = poll(
        FakeFeed({"o/r": [pull(9), pull(8), pull(7)]}), ingress, since
    )
    assert response.next_since == since
    assert [d.ref.number for d in ingress.received if d.ref] == [7, 9]
    (failure,) = response.failures
    assert "503" in failure


def test_a_repository_the_forge_cannot_list_does_not_stop_the_others() -> None:
    feed = FakeFeed(
        {
            "o/down": ForgeUnavailableError("GitHub is down"),
            "o/r": [pull()],
        }
    )
    ingress = FakeIngress()
    response = poll(feed, ingress, NOW - timedelta(hours=1))
    assert len(ingress.received) == 1
    assert response.failures == ("o/down: GitHub is down",)
    assert response.next_since == NOW - timedelta(hours=1)


def test_the_first_poll_asks_for_every_open_pull_request() -> None:
    feed = FakeFeed({"o/r": []})
    response = poll(feed, FakeIngress())
    assert feed.asked == [("o/r", None)]
    assert response.next_since == NOW - OVERLAP


def comment(body: str, comment_id: int = 99) -> PolledComment:
    return PolledComment(
        ref=PullRequestRef(owner="o", repo="r", number=7),
        comment_id=comment_id,
        author="reviewer",
        body=body,
        updated_at=NOW - timedelta(minutes=1),
    )


def test_a_dismissal_comment_is_posted_as_an_issue_comment_delivery() -> None:
    text = "/dismiss ED-01 evidence, not narration"
    feed = FakeFeed({"o/r": []}, {"o/r": [comment(text)]})
    ingress = FakeIngress()
    poll(feed, ingress, NOW - timedelta(hours=1))
    (delivery,) = ingress.received
    assert (delivery.event, delivery.action) == ("issue_comment", "created")
    assert delivery.comment == DeliveryComment(
        comment_id=99, author="reviewer", body=text
    )


def test_other_comments_are_not_posted() -> None:
    feed = FakeFeed({"o/r": []}, {"o/r": [comment("Thanks!")]})
    ingress = FakeIngress()
    poll(feed, ingress, NOW - timedelta(hours=1))
    assert ingress.received == []


def test_a_comment_keeps_its_delivery_id_when_edited() -> None:
    first = delivery_for_comment(comment("/dismiss ED-01 one reason"))
    edited = delivery_for_comment(comment("/dismiss ED-01 another reason"))
    other = delivery_for_comment(
        comment("/dismiss ED-01 one reason", comment_id=100)
    )
    assert first is not None and edited is not None and other is not None
    assert first.delivery_id == edited.delivery_id
    assert other.delivery_id != first.delivery_id


def test_a_first_poll_reads_the_last_days_comments() -> None:
    first = FakeFeed({"o/r": []})
    poll(first, FakeIngress())
    assert first.asked_comments == [("o/r", NOW - COMMENT_LOOKBACK)]
    since = NOW - timedelta(hours=1)
    later = FakeFeed({"o/r": []})
    poll(later, FakeIngress(), since)
    assert later.asked_comments == [("o/r", since)]


def test_comments_are_posted_after_the_pull_requests() -> None:
    feed = FakeFeed(
        {"o/r": [pull(7)]}, {"o/r": [comment("/dismiss ED-01 a reason")]}
    )
    ingress = FakeIngress()
    poll(feed, ingress, NOW - timedelta(hours=1))
    assert [d.event for d in ingress.received] == [
        "pull_request",
        "issue_comment",
    ]


@pytest.mark.parametrize(
    ("text", "watched"),
    [
        ("o/r", WatchedRepository(owner="o", repo="r")),
        (
            "forgejo:o/r.js",
            WatchedRepository(forge="forgejo", owner="o", repo="r.js"),
        ),
    ],
)
def test_a_watched_repository_names_its_forge(
    text: str, watched: WatchedRepository
) -> None:
    assert WatchedRepository.parse(text) == watched
    assert str(watched) == text


@pytest.mark.parametrize("text", ["just-a-name", "gitlab:o/r", "o/r/x"])
def test_anything_else_is_not_a_watched_repository(text: str) -> None:
    with pytest.raises(ValueError, match="not owner/repo"):
        WatchedRepository.parse(text)


def test_each_repository_is_read_from_its_forges_feed() -> None:
    since = NOW - timedelta(hours=1)
    on_forgejo = PullRequestRef(forge="forgejo", owner="o", repo="r", number=8)
    github = FakeFeed({"o/r": [pull(7)]})
    forgejo = FakeFeed({"o/r": [pull(8, ref=on_forgejo)]})
    ingress = FakeIngress()
    PollPullRequestsUseCase(
        {"github": github, "forgejo": forgejo}, ingress, FixedClock()
    ).execute(
        PollPullRequestsRequest(
            repositories=("o/r", "forgejo:o/r"), since=since
        )
    )
    assert [(d.forge, d.ref) for d in ingress.received] == [
        ("github", PullRequestRef(owner="o", repo="r", number=7)),
        ("forgejo", on_forgejo),
    ]
    assert github.asked == forgejo.asked == [("o/r", since)]


def test_a_repository_on_a_forge_with_no_feed_is_a_failure() -> None:
    use_case = PollPullRequestsUseCase(
        {"github": FakeFeed({"o/r": []})}, FakeIngress(), FixedClock()
    )
    response = use_case.execute(
        PollPullRequestsRequest(repositories=("forgejo:o/r", "o/r"))
    )
    assert response.failures == ("forgejo:o/r: no forgejo forge configured",)
    assert response.next_since is None
