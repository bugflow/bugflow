"""A delivery: one event a forge reported."""

from dataclasses import dataclass
from datetime import datetime

from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


@dataclass(frozen=True, kw_only=True)
class DeliveryComment:
    """A comment on a pull request, as a delivery reports it."""

    comment_id: int
    author: str
    body: str


@dataclass(frozen=True, kw_only=True)
class Delivery:
    """One event from a forge, in a form that is the same for every
    forge."""

    #: Which kind of forge sent it: "github" or "forgejo".
    forge: str
    #: The forge's own id for this delivery. If the forge sends the same
    #: delivery again, the id is the same.
    delivery_id: str
    #: The kind of event, such as "pull_request" or "issue_comment".
    event: str
    #: What happened, such as "opened" or "closed". None if the event
    #: has no action.
    action: str | None
    #: The repository as ``owner/name``. None if the event is not about
    #: a repository.
    repository: str | None
    #: The pull request the event is about. None if it is not about one.
    ref: PullRequestRef | None
    #: The comment, for an event about a comment. None otherwise.
    comment: DeliveryComment | None = None
    #: For a delivery that closes a pull request: whether it was merged,
    #: and the commit the merge made. A forge reports "closed" both for
    #: a merge and for a pull request that was abandoned, so this is how
    #: the two are told apart.
    merged: bool = False
    merge_commit_sha: str | None = None
    #: When the forge last changed the pull request. Used to notice that
    #: a polled change was already delivered by a webhook.
    updated_at: datetime | None = None


def forge_time(text: object) -> datetime | None:
    """Read a timestamp as GitHub and Forgejo write them: ISO 8601,
    ending in ``Z`` or an offset. Returns None if ``text`` is empty or
    not a string."""
    if not isinstance(text, str) or not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))
