"""Registering a forge's webhooks, ``bugflow webhooks``, and deleting the
ones left at an old address, ``bugflow prune-webhooks``.

``webhooks`` runs on every deploy. Its job is to make a deploy the moment this
server's declaration takes effect, and to do nothing at all when the
forge already agrees with it.

Everything it needs arrives in the environment. In particular the public
URL: this package does not know where it is deployed, and whoever runs
it holds the route it answers on.

``prune-webhooks`` runs once, after a server has moved to a new public
address and ``webhooks`` has registered it there. The registration
matches by exact URL, so it never sees the webhook at the old address;
this command deletes it.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TextIO

from bugflow.apps.shared.forges import forge_tokens
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
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.correlation import Correlation

#: Every variable this command reads, and does not run without. Named
#: here so a deployment's check can see that the container the command
#: runs in supplies them: a variable the container's file happens not to
#: carry fails the deploy rather than the build.
REQUIRED = ("WATCHED_REPOSITORIES", "INGRESS_URL", "WEBHOOK_SECRET")

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
    def from_environment(cls, environ: Mapping[str, str]) -> "HookSettings":
        """The settings, or ValueError naming what is missing or wrong."""
        repositories = _watched(environ)
        url = _hook_url(environ)
        secret = environ.get("WEBHOOK_SECRET", "")
        if not secret:
            raise ValueError(
                "WEBHOOK_SECRET is not set; a hook registered without one "
                "would post deliveries the ingress answers 401 to"
            )
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
        cls, environ: Mapping[str, str], old_ingress: str
    ) -> "PruneSettings":
        """The settings for deleting the webhooks that point at
        ``old_ingress``, the public address this server answered on
        before. ValueError names what is missing or wrong."""
        repositories = _watched(environ)
        old = old_ingress.strip().rstrip("/")
        if not old:
            raise ValueError(
                "no old address given; it is the public address whose "
                "webhooks are to be deleted"
            )
        return cls(
            repositories=repositories,
            url=f"{old}{ROUTE}",
            keep=_hook_url(environ),
            token=_token(environ, repositories),
        )


def _watched(environ: Mapping[str, str]) -> tuple[WatchedRepository, ...]:
    names = tuple(
        name.strip()
        for name in environ.get("WATCHED_REPOSITORIES", "").split(",")
        if name.strip()
    )
    repositories = []
    for name in names:
        try:
            repository = WatchedRepository.parse(name)
        except ValueError:
            raise ValueError(
                f"WATCHED_REPOSITORIES names {name!r}, not owner/repo"
            ) from None
        if repository.forge != "github":
            raise ValueError(
                f"WATCHED_REPOSITORIES names {name!r}; only github.com "
                "repositories can have their webhooks registered"
            )
        repositories.append(repository)
    return tuple(repositories)


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
        )
    )
    _report(response, settings.url, out)
    return 1 if response.failed else 0


def _report(
    response: ReconcileWebhooksResponse, url: str, out: TextIO
) -> None:
    if not response.outcomes:
        print(
            "no repositories declared; WATCHED_REPOSITORIES is empty",
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
            "no repositories declared; WATCHED_REPOSITORIES is empty",
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
