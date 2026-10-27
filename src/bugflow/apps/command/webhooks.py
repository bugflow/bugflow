"""Registering a forge's webhooks, ``bugflow webhooks``, and deleting the
ones left at an old address, ``bugflow prune-webhooks``.

``webhooks`` runs on every deploy. Its job is to make a deploy the moment this
server's settings take effect, and to do nothing at all when the forge
already agrees with them. The repositories it registers a webhook on are
those on github.com that a gnome judges, read from the settings in the
database ``DATABASE_URL`` names (ADR 008).

Everything it needs arrives in the environment. In particular the public
URL: this package does not know where it is deployed, and whoever runs
it holds the route it answers on.

``prune-webhooks`` runs once, after a server has moved to a new public
address and ``webhooks`` has registered it there. The registration
matches by exact URL, so it never sees the webhook at the old address;
this command deletes it.
"""

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TextIO

from bugflow.apps.shared.forges import forge_tokens
from bugflow.apps.shared.watching import watched
from bugflow.forge.domain.repositories.webhook_admin import (
    WebhookAdminRepository,
)
from bugflow.forge.domain.services.journal_history import (
    JournalRepositoriesService,
)
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.dtos.prune_webhooks import (
    PruneWebhooksRequest,
    PruneWebhooksResponse,
)
from bugflow.forge.dtos.reconcile_webhooks import (
    ReconcileWebhooksRequest,
    ReconcileWebhooksResponse,
)
from bugflow.forge.infrastructure.github import GitHubTokens
from bugflow.forge.usecases.prune_webhooks import PruneWebhooksUseCase
from bugflow.forge.usecases.reconcile_webhooks import ReconcileWebhooksUseCase
from bugflow.review.infrastructure.sqlalchemy_gnome_settings import (
    SqlAlchemyGnomeSettings,
)
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.correlation import Correlation

#: Every variable this command reads, and does not run without. Named
#: here so a deployment's check can see that the container the command
#: runs in supplies them: a variable the container's file happens not to
#: carry fails the deploy rather than the build.
REQUIRED = ("DATABASE_URL", "INGRESS_URL", "WEBHOOK_SECRET")

#: What says which repositories are watched, asked once.
Watching = Callable[[], tuple[WatchedRepository, ...]]

#: The route under the ingress's public address that GitHub posts to.
ROUTE = "/webhooks/github"

#: The order outcomes are reported in: what changed, then what did not.
_ORDER = ["failed", "created", "updated", "removed", "renamed", "unchanged"]


@dataclass(frozen=True)
class HookSettings:
    repositories: tuple[WatchedRepository, ...]
    url: str
    secret: str
    token: GitHubTokens
    origin_endpoint: str = "https://github.com"

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
        watching: Watching | None = None,
    ) -> "HookSettings":
        """The settings, or ValueError naming what is missing or wrong.
        ``watching`` gives the watched repositories; by default, each a
        gnome judges in the settings."""
        url = _hook_url(environ)
        secret = environ.get("WEBHOOK_SECRET", "")
        if not secret:
            raise ValueError(
                "WEBHOOK_SECRET is not set; a hook registered without one "
                "would post deliveries the ingress answers 401 to"
            )
        repositories = _watched(environ, watching)
        return cls(
            repositories=repositories,
            url=url,
            secret=secret,
            token=_token(environ, repositories),
        )


@dataclass(frozen=True)
class PruneSettings:
    repositories: tuple[WatchedRepository, ...]
    url: str
    keep: str
    token: GitHubTokens

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
        old_ingress: str,
        watching: Watching | None = None,
    ) -> "PruneSettings":
        """The settings for deleting the webhooks that point at
        ``old_ingress``, the public address this server answered on
        before. ValueError names what is missing or wrong."""
        old = old_ingress.strip().rstrip("/")
        if not old:
            raise ValueError(
                "no old address given; it is the public address whose "
                "webhooks are to be deleted"
            )
        keep = _hook_url(environ)
        repositories = _watched(environ, watching)
        return cls(
            repositories=repositories,
            url=f"{old}{ROUTE}",
            keep=keep,
            token=_token(environ, repositories),
        )


def _watched(
    environ: Mapping[str, str], watching: Watching | None
) -> tuple[WatchedRepository, ...]:
    """The watched repositories on github.com. A repository on a Forgejo
    has no webhook this command can register, and the poller reads it."""
    if watching is None:
        database_url = environ.get("DATABASE_URL", "")
        if not database_url:
            raise ValueError(
                "DATABASE_URL is not set; the watched repositories are "
                "read from the gnomes' settings there"
            )
        held = SqlAlchemyGnomeSettings(database_url)

        def watching() -> tuple[WatchedRepository, ...]:
            return watched(held)

    return tuple(one for one in watching() if one.forge == "github")


def _hook_url(environ: Mapping[str, str]) -> str:
    url = environ.get("INGRESS_URL", "").rstrip("/")
    if not url:
        raise ValueError(
            "INGRESS_URL is not set. It is the public address a forge "
            "posts deliveries to, which this package does not know"
        )
    return f"{url}{ROUTE}"


def _token(
    environ: Mapping[str, str],
    repositories: tuple[WatchedRepository, ...],
) -> GitHubTokens:
    token = forge_tokens(environ)
    if token is None and repositories:
        raise ValueError(
            "FORGE_TOKEN is not set, nor FORGE_TOKENS_BY_OWNER; "
            "a webhook can be registered or deleted only with a token "
            "that may administer the repository's hooks"
        )
    return token or GitHubTokens()


def run_webhooks(
    settings: HookSettings,
    hooks: WebhookAdminRepository,
    journal: RecordingService,
    remembered: JournalRepositoriesService,
    clock: ClockService,
    out: TextIO,
) -> int:
    """Reconcile, report, and return an exit code.

    Non-zero when any repository failed, so a deploy that could not
    reach the forge is a deploy that says so rather than one that looks
    clean and delivers nothing.
    """
    use_case = ReconcileWebhooksUseCase(hooks, journal, remembered, clock)
    response = use_case.execute(
        ReconcileWebhooksRequest(
            repositories=settings.repositories,
            url=settings.url,
            secret=settings.secret,
            correlation=Correlation(
                workflow_id="webhooks/sync", run_id=uuid.uuid4().hex
            ),
            origin_endpoint=settings.origin_endpoint,
            # A repository whose gnomes are all off keeps its webhook,
            # and one not yet settled is not stripped of it.
            withdraw_dropped=False,
        )
    )
    _report(response, settings.url, out)
    return 1 if response.failed else 0


def _report(
    response: ReconcileWebhooksResponse, url: str, out: TextIO
) -> None:
    if not response.outcomes:
        print(
            "no repository is watched: no gnome judges one on github.com",
            file=out,
        )
        return
    print(f"reconciled against {url}", file=out)
    for outcome in sorted(
        response.outcomes, key=lambda o: _ORDER.index(o.outcome)
    ):
        repository = outcome.repository
        detail = f"  {outcome.detail}" if outcome.detail else ""
        print(
            f"  {outcome.outcome:<10} "
            f"{repository.owner}/{repository.repo}{detail}",
            file=out,
        )


def run_prune(
    settings: PruneSettings,
    hooks: WebhookAdminRepository,
    out: TextIO,
    *,
    dry_run: bool,
) -> int:
    """Delete, or with ``dry_run`` list, the webhooks pointing at the old
    address, report, and return an exit code.

    Raises ``PruneRefusedError`` when the old address is the current
    one. Non-zero when any repository could not be read or changed, so
    a webhook left behind is not reported as gone.
    """
    response = PruneWebhooksUseCase(hooks).execute(
        PruneWebhooksRequest(
            repositories=settings.repositories,
            url=settings.url,
            keep=settings.keep,
            dry_run=dry_run,
        )
    )
    _report_prune(response, settings, out, dry_run=dry_run)
    return 1 if response.failed else 0


#: The order prune outcomes are reported in.
_PRUNE_ORDER = ["failed", "deleted", "would delete", "absent"]


def _report_prune(
    response: PruneWebhooksResponse,
    settings: PruneSettings,
    out: TextIO,
    *,
    dry_run: bool,
) -> None:
    if not response.outcomes:
        print(
            "no repository is watched: no gnome judges one on github.com",
            file=out,
        )
        return
    verb = "would delete" if dry_run else "deleting"
    print(f"{verb} webhooks to {settings.url}", file=out)
    print(f"keeping every other webhook, {settings.keep} among them", file=out)
    for outcome in sorted(
        response.outcomes, key=lambda o: _PRUNE_ORDER.index(o.outcome)
    ):
        repository = outcome.repository
        ids = ", ".join(str(i) for i in outcome.hook_ids)
        detail = f"  hook {ids}" if ids else ""
        detail += f"  {outcome.detail}" if outcome.detail else ""
        print(
            f"  {outcome.outcome:<12} "
            f"{repository.owner}/{repository.repo}{detail}",
            file=out,
        )
    found = sum(len(o.hook_ids) for o in response.outcomes)
    print(
        f"{found} webhook(s) {'to delete' if dry_run else 'deleted'} on "
        f"{len(response.outcomes)} repositories, "
        f"{len(response.failed)} failed",
        file=out,
    )
