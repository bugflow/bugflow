"""Wait for a checkout agent's run to have something to read.

The second of a review's four steps. Nothing is recorded here. What the
run did is recorded when it is collected.
"""

from bugflow.review.domain.errors import AgentUnavailableError
from bugflow.review.domain.services.delegated_work import DelegatedWorkService
from bugflow.review.dtos.wait_review import (
    WaitReviewRequest,
    WaitReviewResponse,
)


class WaitReviewUseCase:
    def __init__(self, agent: DelegatedWorkService) -> None:
        self._agent = agent

    def execute(self, request: WaitReviewRequest) -> WaitReviewResponse:
        """Wait, and return whether the run has something to read.

        If the runner cannot be reached, the answer is "not ready" and
        no error is raised. Collecting is the step that reports a run
        that cannot be read.
        """
        try:
            ready = self._agent.wait(
                request.handle, request.patience or request.handle.patience
            )
        except AgentUnavailableError:
            return WaitReviewResponse(ready=False)
        return WaitReviewResponse(ready=ready)
