"""Pull requests and comments, as the poller reads them from a forge."""

from dataclasses import dataclass
from datetime import datetime

from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

#: The start of the delivery id of every delivery the poller makes up.
#: It lets the receiving side tell a polled delivery from a forge's own.
POLLED_DELIVERY_PREFIX = "poll-"


@dataclass(frozen=True, kw_only=True)
class PolledPullRequest:
    """A pull request as a listing reports it."""

    ref: PullRequestRef
    open: bool
    head_sha: str
    title: str
    body: str
    updated_at: datetime
    closed_at: datetime | None = None


@dataclass(frozen=True, kw_only=True)
class PolledComment:
    """A comment on a pull request as a listing reports it."""

    ref: PullRequestRef
    comment_id: int
    author: str
    body: str
    updated_at: datetime


@dataclass(frozen=True, kw_only=True)
class PullRequestPage:
    """One page of a listing of pull requests."""

    pulls: tuple[PolledPullRequest, ...]
    #: True if this is the last page.
    last: bool
