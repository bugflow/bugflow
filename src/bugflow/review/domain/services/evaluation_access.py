"""Permission to read the recorded evaluations of one pull request."""

from typing import Protocol

from bugflow.shared.domain.values.caller import Caller
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class EvaluationAccessService(Protocol):
    def may_read(
        self, caller: Caller, ref: PullRequestRef, *, origin: str | None = None
    ) -> bool:
        """Whether the verified caller may read this pull request."""
        ...
