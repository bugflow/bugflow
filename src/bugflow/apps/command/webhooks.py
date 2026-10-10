"""Registering a forge's webhooks: ``bugflow webhooks``.

Run on every deploy. Its job is to make a deploy the moment this
server's declaration takes effect, and to do nothing at all when the
forge already agrees with it.

Everything it needs arrives in the environment. In particular the public
URL: this package does not know where it is deployed, and whoever runs
it holds the route it answers on.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TextIO

from bugflow.apps.shared.forges import forge_token
from bugflow.forge.domain.repositories.webhook_admin import (
    WebhookAdminRepository,
)
from bugflow.forge.domain.services.journal_history import (
    JournalRepositoriesService,
)
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.dtos.reconcile_webhooks import (
    ReconcileWebhooksRequest,
    ReconcileWebhooksResponse,
)
from bugflow.forge.usecases.reconcile_webhooks import ReconcileWebhooksUseCase
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.correlation import Correlation

#: Every variable this command reads, and does not run without. Named
#: here so a deployment's check can see that the container the command
#: runs in supplies them: a variable the container's file happens not to
#: carry fails the deploy rather than the build.
REQUIRED = ("WATCHED_REPOSITORIES", "INGRESS_URL", "WEBHOOK_SECRET")

#: The order outcomes are reported in: what changed, then what did not.
_ORDER = ["failed", "created", "updated", "removed", "renamed", "unchanged"]


@dataclass(frozen=True)
class HookSettings:
    repositories: tuple[WatchedRepository, ...]
    url: str
    secret: str
    token: str

    @classmethod
    def from_environment(cls, environ: Mapping[str, str]) -> "HookSettings":
        """The settings, or ValueError naming what is missing or wrong."""
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

        url = environ.get("INGRESS_URL", "").rstrip("/")
        if not url:
            raise ValueError(
                "INGRESS_URL is not set. It is the public address a forge "
                "posts deliveries to, which this package does not know"
            )
        secret = environ.get("WEBHOOK_SECRET", "")
        if not secret:
            raise ValueError(
                "WEBHOOK_SECRET is not set; a hook registered without one "
                "would post deliveries the ingress answers 401 to"
            )
        token = forge_token(environ) or ""
        if not token and repositories:
            raise ValueError(
                "FORGE_TOKEN is not set; registering a webhook needs a "
                "token that may administer the repository's hooks"
            )
        return cls(
            repositories=tuple(repositories),
            url=f"{url}/webhooks/github",
            secret=secret,
            token=token,
        )


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
