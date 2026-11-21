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
``FORGE_TOKEN``, ``FORGE_TOKENS_BY_OWNER`` or a GitHub App's
``FORGE_APP_ID`` for repositories on github.com, and ``FORGEJO_URL`` and
``FORGEJO_TOKEN`` for repositories on a Forgejo.

A repository the forge says was renamed, keeping its owner, has its
gnomes' settings, its boundaries, its withheld share and each of its
archive ledgers whose origin is unresolved moved to the new name, which
is polled at once; the move is logged as a warning.
One moved to another owner, or whose new name the forge would not
give, is a failure, logged as a warning, and its settings stay where
they are until an operator moves them.
"""

import logging
import signal
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta

from bugflow.apps.shared.forges import (
    GITHUB_SETTINGS,
    forge_tokens,
    forgejo_settings,
)
from bugflow.apps.shared.journals import build_sha, stamped_journal
from bugflow.apps.shared.watching import watched_names
from bugflow.archive.dtos.move_ledgers import MoveLedgersRequest
from bugflow.archive.infrastructure.sqlalchemy_bindings import (
    SqlAlchemyBindings,
)
from bugflow.archive.usecases.bind_ledger import BindLedgerUseCase
from bugflow.archive.usecases.move_ledgers import MoveLedgersUseCase
from bugflow.forge.domain.services.polling import PullRequestFeedService
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.dtos.poll_pull_requests import (
    MovedRepository,
    PollPullRequestsRequest,
    PollPullRequestsResponse,
)
from bugflow.forge.infrastructure.forgejo import ForgejoForge
from bugflow.forge.infrastructure.github import GitHubForge, GitHubTokens
from bugflow.forge.infrastructure.webhook_sink import SignedWebhookSink
from bugflow.forge.usecases.poll_pull_requests import PollPullRequestsUseCase
from bugflow.review.dtos.move_repository_settings import (
    MoveRepositorySettingsRequest,
)
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
)
from bugflow.review.infrastructure.sqlalchemy_layer_boundaries import (
    SqlAlchemyLayerBoundaries,
)
from bugflow.review.infrastructure.sqlalchemy_spend_bindings import (
    SqlAlchemySpendBindings,
)
from bugflow.review.infrastructure.sqlalchemy_withholding import (
    SqlAlchemyWithholding,
)
from bugflow.review.usecases.move_repository_settings import (
    MoveRepositorySettingsUseCase,
)
from bugflow.review.usecases.set_gnome import SetGnomeUseCase
from bugflow.shared.infrastructure.system_clock import SystemClock

DEFAULT_INTERVAL_SECONDS = 60.0
DEFAULT_INGRESS_URL = "http://localhost:8000"
#: Who the journal says moved a renamed repository's settings.
MOVED_BY = "bugflow poll"

logger = logging.getLogger(__name__)


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
    #: The build stamped on the journal rows a moved setting writes.
    build: str | None = None

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
                f"none of {GITHUB_SETTINGS} is set, nor FORGEJO_URL and "
                "FORGEJO_TOKEN; the poller does not start without a forge "
                "to poll"
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
            build=build_sha(environ),
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
    poll; by default, each a gnome judges in the settings, where a
    renamed repository's settings are moved to its new name."""
    move: Callable[[str, str], str] | None = None
    if watching is None:
        held = SqlAlchemyGnomeSettings(settings.database_url)

        def watching() -> tuple[str, ...]:
            return watched_names(held)

        move = settings_mover(held, settings)

    stop = threading.Event()
    if not once:
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signal_number, lambda *_: stop.set())
    polls = Polls(poller, settings.forges, watching, out, move)
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
        move: Callable[[str, str], str] | None = None,
    ) -> None:
        """``move`` moves the settings of a repository renamed under the
        same owner, from its old name to its new, and says what it
        moved. Without it, every moved repository is a failure."""
        self._poller = poller
        self._forges = forges
        self._watching = watching
        self._out = out
        self._move = move
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
            fresh = self._followed(
                self._poller.execute(
                    PollPullRequestsRequest(repositories=new, since=None)
                )
            )
            responses.append(fresh)
            if not fresh.failures:
                self._read.update(new)
        if old:
            responses[0] = self._followed(responses[0])
        renamed = tuple(
            one.moved_to
            for response in responses
            for one in response.moved
            if one.moved_to and self._renamed(one)
        )
        if renamed:
            # The new names are polled now, in full, so a deploy's poll
            # misses nothing for the rename.
            again = self._followed(
                self._poller.execute(
                    PollPullRequestsRequest(repositories=renamed, since=None)
                )
            )
            responses.append(again)
            if not again.failures:
                self._read.update(renamed)
        for response in responses:
            for line in render(response):
                self._out(line)
        self._since = responses[0].next_since
        return any(response.failures for response in responses)

    def _renamed(self, one: MovedRepository) -> bool:
        """Whether the repository was renamed under its own owner, on its
        own forge, and its settings can be moved."""
        if self._move is None or one.moved_to is None:
            return False
        try:
            was = WatchedRepository.parse(one.repository)
            now = WatchedRepository.parse(one.moved_to)
        except ValueError:
            return False
        return (
            was.forge == now.forge and was.owner.lower() == now.owner.lower()
        )

    def _followed(
        self, response: PollPullRequestsResponse
    ) -> PollPullRequestsResponse:
        """The response, with each renamed repository's settings moved
        to its new name, and each other moved repository a failure."""
        failures = list(response.failures)
        for one in response.moved:
            if self._renamed(one):
                assert self._move is not None and one.moved_to is not None
                said = self._move(one.repository, one.moved_to)
                logger.warning(
                    "%s was renamed %s; %s",
                    one.repository,
                    one.moved_to,
                    said,
                )
                self._out(
                    f"renamed: {one.repository} is now {one.moved_to}; {said}"
                )
                continue
            failure = f"{one.repository}: {one.reason}"
            if one.moved_to is not None and self._move is not None:
                failure += (
                    "; it has another owner now, so its settings were not "
                    "moved"
                )
            logger.warning("%s", failure)
            failures.append(failure)
        return response.model_copy(update={"failures": tuple(failures)})


def settings_mover(
    held: SqlAlchemyGnomeSettings, settings: PollerSettings
) -> Callable[[str, str], str]:
    """Move a renamed repository's settings, declarations and unresolved
    archive ledgers, each name as watched, and say what was moved. Each
    change is recorded in the journal."""
    journal = stamped_journal(settings.database_url, settings.build)
    clock = SystemClock()
    run_id = uuid.uuid4().hex
    allowances = SqlAlchemySpendBindings(settings.database_url)
    ledgers = SqlAlchemyBindings(settings.database_url)
    mover = MoveRepositorySettingsUseCase(
        held,
        SetGnomeUseCase(held, journal, clock, run_id),
        SqlAlchemyLayerBoundaries(settings.database_url),
        SqlAlchemyWithholding(settings.database_url),
        journal,
        clock,
        run_id,
    )
    ledger_mover = MoveLedgersUseCase(
        ledgers, BindLedgerUseCase(ledgers, journal, clock, run_id)
    )

    def move(was: str, now: str) -> str:
        old, new = WatchedRepository.parse(was), WatchedRepository.parse(now)
        repo, to = f"{old.owner}/{old.repo}", f"{new.owner}/{new.repo}"
        done = mover.execute(
            MoveRepositorySettingsRequest(
                forge=old.forge, repo=repo, to=to, set_by=MOVED_BY
            )
        )
        archived = ledger_mover.execute(
            MoveLedgersRequest(forge=old.forge, repo=repo, to=to)
        )
        said = [f"moved {', '.join(done.moved)}"] if done.moved else []
        if done.kept:
            said.append(f"kept the new name's own {', '.join(done.kept)}")
        if done.boundaries:
            said.append(f"moved its boundary on {', '.join(done.boundaries)}")
        if done.withholding:
            said.append("moved its withheld share")
        if archived.moved:
            said.append(f"moved its ledgers {', '.join(archived.moved)}")
        if archived.stayed:
            said.append(
                f"its ledgers {', '.join(archived.stayed)} have an origin, "
                "so they stay on the old name"
            )
        if any(
            (one.scope.forge, one.scope.repo) == (old.forge, repo)
            for one in allowances.bindings()
        ):
            said.append(
                "its allowances stay on the old name; move them with "
                "bugflow allow"
            )
        return "; ".join(said) or "nothing was set on it"

    return move


def _forge_of(name: str) -> str:
    try:
        return WatchedRepository.parse(name).forge
    except ValueError:
        return ""
