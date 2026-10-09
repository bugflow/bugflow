"""Things a forge can say about a pull request's discussion after it has
closed."""

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class Reaction:
    """One person's reaction to one comment.

    ``content`` is the forge's name for the reaction: "+1", "-1",
    "laugh", "confused", "heart", "hooray", "rocket" or "eyes".
    ``login`` is the person's account name.
    """

    content: str
    login: str
    reacted_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class PullRequestState:
    """How a closed pull request ended: whether it was merged, and the
    last commit on its branch when it closed."""

    merged: bool
    head_sha: str | None = None
