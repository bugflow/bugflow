"""Use case: delete the webhooks that point at an address this server
no longer answers on.

``ReconcileWebhooksUseCase`` matches its own webhook by exact URL, so
when a server moves to a new public address it adds a webhook for the
new one and never sees the old one again. Every delivery is then sent
twice, once to an address that answers nothing or answers from the
server's previous home. This use case removes the old webhook.

The same rule as reconciling: a webhook is deleted only if its URL is
exactly the URL given. A repository's other webhooks, the current
address's included, are left alone. The request is refused outright
when the address to delete is the address this server answers on now.
"""

from urllib.parse import urlsplit

from bugflow.forge.domain.errors import ForgeError
from bugflow.forge.domain.repositories.webhook_admin import (
    WebhookAdminRepository,
)
from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.forge.dtos.prune_webhooks import (
    PrunedRepository,
    PruneWebhooksRequest,
    PruneWebhooksResponse,
)


class PruneRefusedError(ValueError):
    """The prune would delete the webhook this server receives on."""


def same_address(one: str, other: str) -> bool:
    """Whether two URLs name the same address, comparing the scheme and
    the host without regard to case and ignoring a trailing slash.

    Looser than the match that selects a webhook, on purpose: it decides
    a refusal, and a refusal should catch the current address however it
    is spelled.
    """
    a, b = urlsplit(one.strip()), urlsplit(other.strip())
    return (
        a.scheme.lower() == b.scheme.lower()
        and a.netloc.lower() == b.netloc.lower()
        and a.path.rstrip("/") == b.path.rstrip("/")
        and a.query == b.query
    )


class PruneWebhooksUseCase:
    """Takes the repositories to look at, the URL whose webhooks are to
    go and the URL to keep. Returns what was found on each repository:
    deleted, would delete (a dry run), absent or failed.
    """

    def __init__(self, hooks: WebhookAdminRepository) -> None:
        self._hooks = hooks

    def execute(self, request: PruneWebhooksRequest) -> PruneWebhooksResponse:
        if same_address(request.url, request.keep):
            raise PruneRefusedError(
                f"{request.url} is the address this server receives on; "
                "deleting its webhooks would stop every delivery"
            )
        repositories = tuple(dict.fromkeys(request.repositories))
        return PruneWebhooksResponse(
            outcomes=tuple(self._prune(r, request) for r in repositories)
        )

    def _prune(
        self, repo: WatchedRepository, request: PruneWebhooksRequest
    ) -> PrunedRepository:
        try:
            stale = tuple(
                hook.hook_id
                for hook in self._hooks.list_hooks(repo.owner, repo.repo)
                if hook.url == request.url
            )
            if not stale:
                return PrunedRepository(repository=repo, outcome="absent")
            if request.dry_run:
                return PrunedRepository(
                    repository=repo, outcome="would delete", hook_ids=stale
                )
            for hook_id in stale:
                self._hooks.delete_hook(repo.owner, repo.repo, hook_id)
            return PrunedRepository(
                repository=repo, outcome="deleted", hook_ids=stale
            )
        except ForgeError as exc:
            # One repository the forge refuses must not keep the old
            # webhook on the others. It is reported, and the run fails.
            return PrunedRepository(
                repository=repo, outcome="failed", detail=str(exc)
            )
