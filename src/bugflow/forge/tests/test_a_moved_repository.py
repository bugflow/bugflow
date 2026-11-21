"""Tests of a repository the forge redirects the poller's listing for.

The listing is refused, not followed, so nothing read under the new name
is taken as the old name's. The adapter asks the forge for the
repository's name now, on the forge's own host, and the poll reports the
repository as moved, with that name, rather than as a failure.
"""

from datetime import UTC, datetime

import httpx2
import pytest

from bugflow.forge.domain.errors import ForgeRepositoryMovedError
from bugflow.forge.dtos.poll_pull_requests import (
    MovedRepository,
    PollPullRequestsRequest,
)
from bugflow.forge.infrastructure.forgejo import ForgejoForge
from bugflow.forge.infrastructure.github import GitHubForge
from bugflow.forge.tests.test_poll_pull_requests import (
    FakeFeed,
    FakeIngress,
    FixedClock,
)
from bugflow.forge.usecases.poll_pull_requests import PollPullRequestsUseCase

THEN = datetime(2026, 9, 10, tzinfo=UTC)


def renamed_on_github(seen: list[str]) -> GitHubForge:
    """GitHub, where ``o/old`` was renamed ``o/new``: a request under the
    old name is sent to the repository's id."""

    def serve(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        path = request.url.path
        if path.startswith("/repos/o/old"):
            rest = path.removeprefix("/repos/o/old")
            return httpx2.Response(
                301,
                headers={"Location": f"/repositories/123{rest}"},
            )
        if path == "/repositories/123":
            return httpx2.Response(200, json={"full_name": "o/new"})
        return httpx2.Response(200, json=[])

    return GitHubForge("t", transport=httpx2.MockTransport(serve))


def renamed_on_forgejo(seen: list[str]) -> ForgejoForge:
    """A Forgejo, where ``o/old`` was renamed ``o/new``: a request under
    the old name is sent to the new."""

    def serve(request: httpx2.Request) -> httpx2.Response:
        seen.append(request.url.path)
        path = request.url.path
        if path.startswith("/api/v1/repos/o/old"):
            rest = path.removeprefix("/api/v1/repos/o/old")
            return httpx2.Response(
                301,
                headers={
                    "Location": f"https://forge.test/api/v1/repos/o/new{rest}"
                },
            )
        if path == "/api/v1/repos/o/new":
            return httpx2.Response(200, json={"full_name": "o/new"})
        return httpx2.Response(200, json=[])

    return ForgejoForge(
        "https://forge.test", "t", transport=httpx2.MockTransport(serve)
    )


@pytest.mark.parametrize("comments", [False, True])
def test_github_names_where_the_repository_went(comments: bool) -> None:
    seen: list[str] = []
    forge = renamed_on_github(seen)
    with pytest.raises(ForgeRepositoryMovedError) as refused:
        if comments:
            forge.updated_comments("o", "old", THEN)
        else:
            forge.updated_pull_requests("o", "old", None)
    assert (refused.value.repository, refused.value.moved_to) == (
        "o/old",
        "o/new",
    )
    assert "is now o/new" in str(refused.value)
    # Only the repository's name is read under its new address.
    assert [p for p in seen if p.startswith("/repositories")] == [
        "/repositories/123"
    ]


@pytest.mark.parametrize("comments", [False, True])
def test_forgejo_names_where_the_repository_went(comments: bool) -> None:
    seen: list[str] = []
    forge = renamed_on_forgejo(seen)
    with pytest.raises(ForgeRepositoryMovedError) as refused:
        if comments:
            forge.updated_comments("o", "old", THEN)
        else:
            forge.updated_pull_requests("o", "old", None)
    assert refused.value.moved_to == "o/new"
    assert [p for p in seen if p.startswith("/api/v1/repos/o/new")] == [
        "/api/v1/repos/o/new"
    ]


def test_a_new_name_on_another_host_is_not_asked_for() -> None:
    seen: list[str] = []

    def serve(request: httpx2.Request) -> httpx2.Response:
        seen.append(str(request.url))
        return httpx2.Response(
            301, headers={"Location": "https://other.test/repos/o/new"}
        )

    forge = GitHubForge("t", transport=httpx2.MockTransport(serve))
    with pytest.raises(ForgeRepositoryMovedError) as refused:
        forge.updated_pull_requests("o", "old", None)
    assert refused.value.moved_to is None
    assert "did not say where it is now" in str(refused.value)
    assert all("other.test" not in url for url in seen)


@pytest.mark.parametrize(
    ("watched", "moved_to"),
    [("o/old", "o/new"), ("forgejo:o/old", "forgejo:o/new")],
)
def test_a_poll_reports_a_moved_repository_apart_from_failures(
    watched: str, moved_to: str
) -> None:
    feed = FakeFeed(
        {
            "o/old": ForgeRepositoryMovedError(
                "o/old is now o/new", "o/old", "o/new"
            ),
            "o/r": [],
        }
    )
    poll = PollPullRequestsUseCase(
        {"github": feed, "forgejo": feed}, FakeIngress(), FixedClock()
    )
    answered = poll.execute(
        PollPullRequestsRequest(repositories=(watched, "o/r"), since=THEN)
    )
    assert answered.moved == (
        MovedRepository(
            repository=watched,
            moved_to=moved_to,
            reason="o/old is now o/new",
        ),
    )
    assert answered.failures == ()
    # The period is read again next time, as after a failure.
    assert answered.next_since == THEN


def test_a_repository_whose_new_name_is_unknown_is_moved_to_none() -> None:
    feed = FakeFeed(
        {"o/old": ForgeRepositoryMovedError("moved", "o/old", None)}
    )
    poll = PollPullRequestsUseCase(
        {"github": feed}, FakeIngress(), FixedClock()
    )
    answered = poll.execute(PollPullRequestsRequest(repositories=("o/old",)))
    assert answered.moved[0].moved_to is None
