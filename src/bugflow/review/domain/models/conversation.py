"""What this context reads of a pull request's conversation after the
pull request has closed."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class Reaction:
    """One person's reaction to one comment."""

    #: The reaction, by the forge's name for it, such as "+1".
    content: str
    #: The person's user name on the forge.
    login: str
    reacted_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class Closing:
    """How a pull request closed."""

    #: True if it was merged, False if it was closed without merging.
    merged: bool
    #: Its last commit when it closed, if known.
    head_sha: str | None = None
