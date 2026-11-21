"""The request and response of ``PollPullRequestsUseCase``."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from bugflow.forge.domain.models.delivery import Delivery


class PollPullRequestsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    # The repositories to poll, each as ``owner/repo`` for GitHub or
    # ``forgejo:owner/repo`` for Forgejo.
    repositories: tuple[str, ...]
    # Read changes since this time. None means read every open pull request.
    since: datetime | None = None


class SentDelivery(BaseModel):
    model_config = ConfigDict(frozen=True)

    delivery: Delivery
    # What the server did with the delivery: evaluate, close, dismiss,
    # duplicate or ignored.
    outcome: str


class MovedRepository(BaseModel):
    """A repository the forge answered for with a redirect, so it was
    not read."""

    model_config = ConfigDict(frozen=True)

    # As it was asked for: ``owner/repo``, or ``forgejo:owner/repo``.
    repository: str
    # The name the forge gives it now, in the same form, or None where
    # the forge did not say.
    moved_to: str | None
    # What the forge said, to report.
    reason: str


class PollPullRequestsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    sent: tuple[SentDelivery, ...]
    failures: tuple[str, ...]
    # The repositories that moved. They are not among ``failures``: what
    # to do about each is the caller's to decide.
    moved: tuple[MovedRepository, ...] = ()
    # The ``since`` to give the next poll.
    next_since: datetime | None
