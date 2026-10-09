"""The interface for managing a repository's webhooks on a forge.

It is separate from ``ForgeService`` because it works on a repository,
where ``ForgeService`` works on one pull request, and because few
implementations of ``ForgeService`` have any reason to manage webhooks.

Every method may raise ``ForgeError`` or one of its subclasses.
"""

from typing import Protocol

from bugflow.forge.domain.models.webhook import Webhook
from bugflow.shared.domain.repositories.base import BaseRepository


class WebhookAdminRepository(BaseRepository[Webhook], Protocol):
    def list_hooks(self, owner: str, repo: str) -> list[Webhook]:
        """Every webhook on the repository, including ones somebody else
        created."""
        ...

    def create_hook(
        self,
        owner: str,
        repo: str,
        url: str,
        secret: str,
        events: frozenset[str],
    ) -> Webhook:
        """Add a webhook that posts JSON to ``url`` for ``events``,
        signed with ``secret``."""
        ...

    def update_hook(
        self,
        owner: str,
        repo: str,
        hook_id: int,
        url: str,
        secret: str,
        events: frozenset[str],
    ) -> Webhook:
        """Set an existing webhook's URL, secret and events.

        The secret is always written. A forge does not give a secret
        back, so there is no way to check whether the one it has is
        current.
        """
        ...

    def delete_hook(self, owner: str, repo: str, hook_id: int) -> None:
        """Remove the webhook. Removing one that is already gone is not
        an error."""
        ...

    def current_name(self, owner: str, repo: str) -> str | None:
        """The repository's present ``owner/name``, or None if it no
        longer exists.

        A forge still answers for a renamed repository under its old
        name. This returns the new name, so the caller can tell a renamed
        repository from one that is no longer watched.
        """
        ...
