"""The interfaces the poller uses.

The poller is for a server that a forge cannot reach with deliveries. It
asks the forge what has changed and posts each change to the server's
own delivery endpoint, in the form the forge would have sent.
"""

from datetime import datetime
from typing import Protocol

from bugflow.forge.domain.models.delivery import Delivery
from bugflow.forge.domain.models.polling import (
    PolledComment,
    PolledPullRequest,
)


class PullRequestFeedService(Protocol):
    """Lists what has changed in a repository. Both methods may raise
    ``ForgeError``."""

    def updated_pull_requests(
        self, owner: str, repo: str, since: datetime | None
    ) -> list[PolledPullRequest]:
        """Pull requests changed since ``since``, most recently changed
        first. If ``since`` is None, every open pull request."""
        ...

    def updated_comments(
        self, owner: str, repo: str, since: datetime
    ) -> list[PolledComment]:
        """Comments on the repository's pull requests changed since
        ``since``, oldest first."""
        ...


class DeliverySinkService(Protocol):
    def send(self, delivery: Delivery) -> str:
        """Post the delivery to the server's delivery endpoint and return
        the outcome the server reported. Raises
        ``DeliveryNotAcceptedError`` if the server did not accept it."""
        ...
