"""The request and response of ``EvaluatePullRequestUseCase``.

A workflow engine records both. Renaming a field or changing its type
breaks the replay of every evaluation that is running.
"""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.finding import Finding
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class EvaluatePullRequestRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    # False to judge nothing.
    use_judge: bool = True
    # False for an evaluation that must write nothing to the pull
    # request, such as one of a pull request that closed long ago.
    publish: bool = True
    # The forge deliveries this evaluation answers. Empty if it was
    # started by hand.
    delivery_ids: tuple[str, ...] = ()


class EvaluatePullRequestResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    title: str
    head_branch: str
    base_branch: str
    commit_count: int
    file_count: int
    changed_lines: int
    corpus_version: str
    findings: tuple[Finding, ...]
    judge_status: str
    publish_status: str
    # The findings the previous evaluation raised and this one
    # withdrew.
    resolved: tuple[Finding, ...] = ()
    # The workflow run the evaluation ran in.
    workflow_id: str
    run_id: str
