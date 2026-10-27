"""The poller: a stand-in for a forge webhook.

Where the forge cannot reach the ingress, as on a laptop, the poller
lists the watched repositories' pull requests with the forge token and
posts each change to the ingress as a signed delivery, shaped as its
forge would send it. Run as ``bugflow poll``.

It polls each repository a gnome judges, read from the settings in the
database ``DATABASE_URL`` names before every poll (ADR 008), so a gnome
set on a repository is polled without a restart. A repository is read
in full the first time it is polled, and one on a forge the poller has
no credentials for is said and not polled.

Configured from the environment: ``DATABASE_URL``,
``POLL_INTERVAL_SECONDS``, ``INGRESS_URL``, ``WEBHOOK_SECRET``,
``FORGE_TOKEN`` for repositories on github.com, and ``FORGEJO_URL`` and
``FORGEJO_TOKEN`` for repositories on a Forgejo.
"""

import signal
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from bugflow.apps.shared.forges import forge_tokens, forgejo_settings
from bugflow.apps.shared.watching import watched_names
from bugflow.forge.domain.services.polling import PullRequestFeedService
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.dtos.poll_pull_requests import (
    PollPullRequestsRequest,
    PollPullRequestsResponse,
)
from bugflow.forge.infrastructure.forgejo import ForgejoForge
from bugflow.forge.infrastructure.github import GitHubForge, GitHubTokens
from bugflow.forge.infrastructure.webhook_sink import SignedWebhookSink
from bugflow.forge.usecases.poll_pull_requests import PollPullRequestsUseCase
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
)
from bugflow.shared.infrastructure.system_clock import SystemClock

DEFAULT_INTERVAL_SECONDS = 60.0
DEFAULT_INGRESS_URL = "http://localhost:8000"


@dataclass(frozen=True)
class PollerSettings:
    #: Where the gnomes' settings are kept.
    database_url: str
    interval: timedelta
    ingress_url: str
    secret: str
    # github.com's tokens, when a repository there is watched.
    token: GitHubTokens | None
    # The Forgejo's URL and token, when a repository there is watched.
    forgejo: tuple[str, str] | None = None

    @property
    def forges(self) -> frozenset[str]:
        """The forges this poller has credentials for."""
        return frozenset(
            name
            for name, held in (
                ("github", self.token),
                ("forgejo", self.forgejo),
            )
            if held
        )

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "PollerSettings":
        """The settings, or ValueError naming what is missing or wrong."""
        database_url = environ.get("DATABASE_URL", "")
        if not database_url:
            raise ValueError(
                "DATABASE_URL is not set; the poller reads which "
                "repositories to poll from the gnomes' settings there"
            )
        secret = environ.get("WEBHOOK_SECRET", "")
        if not secret:
            raise ValueError(
                "WEBHOOK_SECRET is not set; the poller does not start "
                "without it"
            )
        token = forge_tokens(environ)
        forgejo = forgejo_settings(environ)
        if token is None and forgejo is None:
            raise ValueError(
                "FORGE_TOKEN is not set, nor FORGE_TOKENS_BY_OWNER, nor "
                "FORGEJO_URL and FORGEJO_TOKEN; the poller does not start "
                "without a forge to poll"
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
            database_url=database_url,
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
    watching: Callable[[], tuple[str, ...]] | None = None,
) -> int:
    """Poll until stopped, or once. Exits 1 when a single poll had
    failures.

    ``watching`` says which repositories to poll, asked before each
    poll; by default, each a gnome judges in the settings."""
    if watching is None:
        held = SqlAlchemyGnomeSettings(settings.database_url)

        def watching() -> tuple[str, ...]:
            return watched_names(held)

    stop = threading.Event()
    if not once:
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signal_number, lambda *_: stop.set())
    polls = Polls(poller, settings.forges, watching, out)
    while True:
        failed = polls.poll()
        if once:
            return 1 if failed else 0
        if stop.wait(settings.interval.total_seconds()):
            return 0


class Polls:
    """One poll after another, each of the repositories watched then.

    A repository on a forge the poller has no credentials for is not
    polled, and is said once. A repository is read in full the first
    time it is polled, so one watched after the poller began has its
    open pull requests delivered; after that, it is read from the last
    poll."""

    def __init__(
        self,
        poller: PollPullRequestsUseCase,
        forges: frozenset[str],
        watching: Callable[[], tuple[str, ...]],
        out: Callable[[str], None],
    ) -> None:
        self._poller = poller
        self._forges = forges
        self._watching = watching
        self._out = out
        self._since: datetime | None = None
        self._read: set[str] = set()
        self._unpolled: tuple[str, ...] = ()

    def poll(self) -> bool:
        """Poll once. True where any repository failed."""
        names = self._watching()
        skipped = tuple(o for o in names if _forge_of(o) not in self._forges)
        if skipped and skipped != self._unpolled:
            self._out(
                "not polled, no credentials for their forge: "
                + ", ".join(skipped)
            )
        self._unpolled = skipped
        polled = tuple(one for one in names if one not in skipped)
        old = tuple(o for o in polled if o in self._read and self._since)
        new = tuple(one for one in polled if one not in old)
        responses = []
        if old:
            responses.append(
                self._poller.execute(
                    PollPullRequestsRequest(
                        repositories=old, since=self._since
                    )
                )
            )
        if new or not old:
            fresh = self._poller.execute(
                PollPullRequestsRequest(repositories=new, since=None)
            )
            responses.append(fresh)
            if not fresh.failures:
                self._read.update(new)
        for response in responses:
            for line in render(response):
                self._out(line)
        self._since = responses[0].next_since
        return any(response.failures for response in responses)


def _forge_of(name: str) -> str:
    try:
        return WatchedRepository.parse(name).forge
    except ValueError:
        return ""
