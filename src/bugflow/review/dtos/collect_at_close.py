"""The request and response of ``CollectAtCloseUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class CollectAtCloseRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    # The workflow run of the pull request, under which the facts are
    # recorded.
    correlation: Correlation


class CollectAtCloseResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    # How many reactions were recorded.
    reactions: int
    merged: bool
    # How many findings were still standing.
    outstanding: int
