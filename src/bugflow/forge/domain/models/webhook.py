"""A webhook on a repository.

Only the fields needed to compare a webhook with what is wanted are kept.
A forge reports more.

The webhook's secret is not here. A forge never gives a secret back, so
there is nothing to compare. The secret is therefore written every time
a webhook is created or updated.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Webhook:
    """One webhook on one repository."""

    hook_id: int
    url: str
    events: frozenset[str]
    active: bool

    def matches(self, url: str, events: frozenset[str]) -> bool:
        """Whether this webhook already sends ``events`` to ``url`` and is
        switched on.

        The URL must be exactly equal. A forge treats a URL with a
        trailing slash as a different one, and so does this.
        """
        return self.url == url and self.events == events and self.active
