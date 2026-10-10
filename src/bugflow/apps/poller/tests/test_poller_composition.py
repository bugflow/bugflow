"""How the poller assembles itself from its environment."""

from datetime import timedelta

import pytest

from bugflow.apps.poller.poller import (
    DEFAULT_INGRESS_URL,
    PollerSettings,
    render,
    run_poller,
)
from bugflow.forge.domain.models.delivery import Delivery
from bugflow.forge.dtos.poll_pull_requests import (
    PollPullRequestsRequest,
    PollPullRequestsResponse,
    SentDelivery,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

ENVIRON = {
    "POLL_REPOSITORIES": "o/r, o/other",
    "WEBHOOK_SECRET": "s",
    "FORGE_TOKEN": "t",
}


def test_settings_from_the_environment() -> None:
    settings = PollerSettings.from_environment(ENVIRON)
    assert settings.repositories == ("o/r", "o/other")
    assert settings.interval == timedelta(seconds=60)
    assert settings.ingress_url == DEFAULT_INGRESS_URL


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"POLL_REPOSITORIES": ""}, "POLL_REPOSITORIES is not set"),
        ({"POLL_REPOSITORIES": "just-a-name"}, "not owner/repo"),
        ({"WEBHOOK_SECRET": ""}, "WEBHOOK_SECRET is not set"),
        ({"FORGE_TOKEN": ""}, "FORGE_TOKEN is not set"),
        (
            {"POLL_REPOSITORIES": "o/r, forgejo:o/r"},
            "FORGEJO_URL and FORGEJO_TOKEN are not both set",
        ),
        ({"POLL_INTERVAL_SECONDS": "0"}, "not a positive number"),
        ({"POLL_INTERVAL_SECONDS": "soon"}, "not a positive number"),
    ],
)
def test_the_poller_does_not_start_with_a_missing_or_wrong_setting(
    change: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        PollerSettings.from_environment(ENVIRON | change)


def test_watching_only_forgejo_needs_no_github_token() -> None:
    settings = PollerSettings.from_environment(
        {
            "POLL_REPOSITORIES": "forgejo:o/r",
            "WEBHOOK_SECRET": "s",
            "FORGEJO_URL": "http://forgejo.example",
            "FORGEJO_TOKEN": "f",
        }
    )
    assert settings.token is None
    assert settings.forgejo == ("http://forgejo.example", "f")


def sent(number: int, outcome: str) -> SentDelivery:
    delivery = Delivery(
        forge="github",
        delivery_id=f"poll-{number}",
        event="pull_request",
        action="synchronize",
        repository="o/r",
        ref=PullRequestRef(owner="o", repo="r", number=number),
    )
    return SentDelivery(delivery=delivery, outcome=outcome)


def test_duplicates_are_counted_not_listed() -> None:
    response = PollPullRequestsResponse(
        sent=(sent(7, "evaluate"), sent(8, "duplicate")),
        failures=("o/r#9: the ingress answered 503",),
        next_since=None,
    )
    assert render(response) == [
        "o/r#7 synchronize poll-7 -> evaluate",
        "failed: o/r#9: the ingress answered 503",
        "polled: 2 posted, 1 duplicate, 1 failed",
    ]


class RecordingPoller:
    def __init__(self, response: PollPullRequestsResponse) -> None:
        self.response = response
        self.requests: list[PollPullRequestsRequest] = []

    def execute(
        self, request: PollPullRequestsRequest
    ) -> PollPullRequestsResponse:
        self.requests.append(request)
        return self.response


@pytest.mark.parametrize(("failures", "status"), [((), 0), (("x",), 1)])
def test_a_single_poll_exits_with_whether_it_failed(
    failures: tuple[str, ...], status: int
) -> None:
    poller = RecordingPoller(
        PollPullRequestsResponse(sent=(), failures=failures, next_since=None)
    )
    lines: list[str] = []
    settings = PollerSettings.from_environment(ENVIRON)
    assert run_poller(poller, settings, once=True, out=lines.append) == status  # type: ignore[arg-type]
    assert poller.requests == [
        PollPullRequestsRequest(repositories=("o/r", "o/other"), since=None)
    ]
    assert lines[-1].startswith("polled:")
