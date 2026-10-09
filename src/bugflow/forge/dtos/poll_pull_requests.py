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


class PollPullRequestsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    sent: tuple[SentDelivery, ...]
    failures: tuple[str, ...]
    # The ``since`` to give the next poll.
    next_since: datetime | None
