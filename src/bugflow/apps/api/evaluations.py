"""HTTP reads of evaluation evidence after pull-request access checks."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Path, Query

from bugflow.review.domain.errors import (
    HistoryTooLargeError,
    ReviewRecordNotFoundError,
)
from bugflow.review.domain.models.history import HistoryScope
from bugflow.review.domain.services.evaluation_access import (
    EvaluationAccessService,
)
from bugflow.review.dtos.read_review_record import (
    ReadReviewHistoryRequest,
    ReadReviewHistoryResponse,
    ReadReviewRecordRequest,
    ReadReviewRecordResponse,
)
from bugflow.review.usecases.read_review_record import (
    ReadReviewHistoryUseCase,
    ReadReviewRecordUseCase,
)
from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.domain.values.correlation import Correlation
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

Component = Annotated[
    str, Path(pattern=r"^[\w.-]+$", min_length=1, max_length=255)
]
Number = Annotated[int, Query(gt=0)]
Identifier = Annotated[
    str, Query(min_length=1, max_length=1024, pattern=r"\S")
]
Forge = Literal["github", "forgejo"]


@dataclass(frozen=True)
class EvaluationReading:
    access: EvaluationAccessService
    history: ReadReviewHistoryUseCase
    detail: ReadReviewRecordUseCase


def evaluation_routes(
    app: FastAPI, caller: Callable[..., Caller], reading: EvaluationReading
) -> None:
    prefix = "/api/repositories/{forge}/{owner}/{repo}"

    def require_access(who: Caller, ref: PullRequestRef) -> None:
        if not reading.access.may_read(who, ref):
            raise HTTPException(
                403, "this caller may not read this evaluation"
            )

    @app.get(prefix + "/evaluations")
    def history(
        who: Annotated[Caller, Depends(caller)],
        forge: Forge,
        owner: Component,
        repo: Component,
        pr_number: Annotated[
            list[Number], Query(min_length=1, max_length=100)
        ],
        policy_id: Annotated[
            str | None, Query(min_length=1, max_length=255)
        ] = None,
    ) -> ReadReviewHistoryResponse:
        # Refuse the whole request if even one selected PR is inaccessible.
        numbers = tuple(sorted(set(pr_number)))
        for number in numbers:
            require_access(
                who,
                PullRequestRef(
                    forge=forge, owner=owner, repo=repo, number=number
                ),
            )
        try:
            return reading.history.execute(
                ReadReviewHistoryRequest(
                    scope=HistoryScope(
                        forge=forge, repo=f"{owner}/{repo}", pr_numbers=numbers
                    ),
                    policy_id=policy_id,
                )
            )
        except HistoryTooLargeError as exc:
            raise HTTPException(413, str(exc)) from exc

    @app.get(prefix + "/pull-requests/{pr_number}/evaluation")
    def detail(
        who: Annotated[Caller, Depends(caller)],
        forge: Forge,
        owner: Component,
        repo: Component,
        pr_number: Annotated[int, Path(gt=0)],
        workflow_id: Identifier,
        run_id: Identifier,
    ) -> ReadReviewRecordResponse:
        ref = PullRequestRef(
            forge=forge, owner=owner, repo=repo, number=pr_number
        )
        require_access(who, ref)
        try:
            return reading.detail.execute(
                ReadReviewRecordRequest(
                    ref=ref,
                    correlation=Correlation(
                        workflow_id=workflow_id, run_id=run_id
                    ),
                )
            )
        except ReviewRecordNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except HistoryTooLargeError as exc:
            raise HTTPException(413, str(exc)) from exc
