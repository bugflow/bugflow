"""The request and response of ``ObservePullRequestUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.forge.domain.models.pull_request import (
    PullRequestSummary,
    SnapshotRef,
)
from bugflow.forge.domain.values.evaluation_regime import EvaluationRegime
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ObservePullRequestRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    correlation: Correlation
    delivery_ids: tuple[str, ...] = ()
    # The ids of the policies this pull request would be reviewed against now.
    # They are used to decide whether it has already been reviewed against all
    # of them. Empty means: ask only whether it has been reviewed at all.
    declared: tuple[str, ...] = ()


class ObservePullRequestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot: SnapshotRef
    summary: PullRequestSummary
    corpus: EvaluationRegime
    # True if this exact content has already been reviewed under the rules now
    # in force. Reviewing it again would ask the same questions about the same
    # text and pay for the same answers.
    judged_before: bool = False
