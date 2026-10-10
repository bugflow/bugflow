"""The poller: a stand-in for a forge webhook.

Where the forge cannot reach the ingress, as on a laptop, the poller
lists the watched repositories' pull requests with the forge token and
posts each change to the ingress as a signed delivery, shaped as its
forge would send it. Run as ``bugflow poll``.

Configured from the environment: ``POLL_REPOSITORIES``,
``POLL_INTERVAL_SECONDS``, ``INGRESS_URL``, ``WEBHOOK_SECRET``,
``FORGE_TOKEN`` for repositories on github.com, and ``FORGEJO_URL`` and
``FORGEJO_TOKEN`` for repositories on a Forgejo.
"""

import signal
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from bugflow.apps.shared.forges import forge_token, forgejo_settings
from bugflow.forge.domain.services.polling import PullRequestFeedService
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.dtos.poll_pull_requests import (
    PollPullRequestsRequest,
    PollPullRequestsResponse,
)
from bugflow.forge.infrastructure.forgejo import ForgejoForge
from bugflow.forge.infrastructure.github import GitHubForge
from bugflow.forge.infrastructure.webhook_sink import SignedWebhookSink
from bugflow.forge.usecases.poll_pull_requests import PollPullRequestsUseCase
from bugflow.shared.infrastructure.system_clock import SystemClock

DEFAULT_INTERVAL_SECONDS = 60.0
DEFAULT_INGRESS_URL = "http://localhost:8000"


@dataclass(frozen=True)
class PollerSettings:
    repositories: tuple[str, ...]
    interval: timedelta
    ingress_url: str
    secret: str
    # github.com's token, when a repository there is watched.
    token: str | None
    # The Forgejo's URL and token, when a repository there is watched.
    forgejo: tuple[str, str] | None = None

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "PollerSettings":
        """The settings, or ValueError naming what is missing or wrong."""
        repositories = tuple(
            name.strip()
            for name in environ.get("POLL_REPOSITORIES", "").split(",")
            if name.strip()
        )
        if not repositories:
            raise ValueError(
                "POLL_REPOSITORIES is not set; the poller does not start "
                "without it"
            )
        forges: set[str] = set()
        for name in repositories:
            try:
                forges.add(WatchedRepository.parse(name).forge)
            except ValueError:
                raise ValueError(
                    f"POLL_REPOSITORIES names {name!r}, not owner/repo or "
                    "forgejo:owner/repo"
                ) from None
        secret = environ.get("WEBHOOK_SECRET", "")
        if not secret:
            raise ValueError(
                "WEBHOOK_SECRET is not set; the poller does not start "
                "without it"
            )
        token = forge_token(environ)
        if token is None and "github" in forges:
            raise ValueError(
                "FORGE_TOKEN is not set; the poller does not start without it"
            )
        forgejo = forgejo_settings(environ)
        if forgejo is None and "forgejo" in forges:
            raise ValueError(
                "FORGEJO_URL and FORGEJO_TOKEN are not both set; the poller "
                "does not watch a repository on Forgejo without them"
            )
        raw_interval = environ.get("POLL_INTERVAL_SECONDS") or str(
            DEFAULT_INTERVAL_SECONDS
        )
        try:
            seconds = float(raw_interval)
        except ValueError:
            seconds = 0.0
        if seconds <= 0:
            raise ValueError(
                f"POLL_INTERVAL_SECONDS is {raw_interval!r}, not a positive "
                "number"
            )
        return cls(
            repositories=repositories,
            interval=timedelta(seconds=seconds),
            ingress_url=environ.get("INGRESS_URL") or DEFAULT_INGRESS_URL,
            secret=secret,
            token=token,
            forgejo=forgejo,
        )


def poller_from_settings(settings: PollerSettings) -> PollPullRequestsUseCase:
    feeds: dict[str, PullRequestFeedService] = {}
    if settings.token:
        feeds["github"] = GitHubForge(settings.token)
    if settings.forgejo:
        feeds["forgejo"] = ForgejoForge(*settings.forgejo)
    return PollPullRequestsUseCase(
        feeds,
        SignedWebhookSink(settings.ingress_url, settings.secret),
        SystemClock(),
    )


def render(response: PollPullRequestsResponse) -> list[str]:
    """What a poll did. Duplicates are counted, not listed."""
    lines = [
        f"{sent.delivery.ref} {sent.delivery.action} "
        f"{sent.delivery.delivery_id} -> {sent.outcome}"
        for sent in response.sent
        if sent.outcome != "duplicate"
    ]
    lines += [f"failed: {failure}" for failure in response.failures]
    duplicates = sum(1 for s in response.sent if s.outcome == "duplicate")
    lines.append(
        f"polled: {len(response.sent)} posted, {duplicates} duplicate, "
        f"{len(response.failures)} failed"
    )
    return lines


def run_poller(
    poller: PollPullRequestsUseCase,
    settings: PollerSettings,
    once: bool = False,
    out: Callable[[str], None] = print,
) -> int:
    """Poll until stopped, or once. Exits 1 when a single poll had
    failures."""
    stop = threading.Event()
    if not once:
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signal_number, lambda *_: stop.set())
    since: datetime | None = None
    while True:
        response = poller.execute(
            PollPullRequestsRequest(
                repositories=settings.repositories, since=since
            )
        )
        for line in render(response):
            out(line)
        since = response.next_since
        if once:
            return 1 if response.failures else 0
        if stop.wait(settings.interval.total_seconds()):
            return 0
