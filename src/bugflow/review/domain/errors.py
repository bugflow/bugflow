"""The errors this context raises."""

from datetime import timedelta

from bugflow.shared.domain.models.call_record import CallRecord


class JudgeUnavailableError(Exception):
    """The judge refused or could not answer.

    The evaluation carries on without that policy's findings and says
    so.

    ``calls`` are the calls to the model that were made before the
    failure. They are carried here so that they can still be recorded:
    a call that was refused may still have cost something.
    """

    def __init__(
        self, message: str, calls: tuple[CallRecord, ...] = ()
    ) -> None:
        super().__init__(message)
        self.calls = calls


class JudgeTemporarilyUnavailableError(JudgeUnavailableError):
    """The judge could not answer now, and the same request may succeed
    later: a rate limit, an overloaded provider, a server error or a
    timeout.

    ``retry_after`` is how long to wait before trying again, if known.
    """

    def __init__(
        self,
        message: str,
        retry_after: timedelta | None = None,
        calls: tuple[CallRecord, ...] = (),
    ) -> None:
        super().__init__(message, calls)
        self.retry_after = retry_after


class GraderUnavailableError(Exception):
    """The grader could not be asked, or did not answer. The step that
    asked is tried again.

    ``calls`` are the calls to the model that were made, so that they
    can still be recorded.
    """

    def __init__(
        self, message: str, calls: tuple[CallRecord, ...] = ()
    ) -> None:
        super().__init__(message)
        self.calls = calls


class ExchangeNotFoundError(Exception):
    """No judge exchange is stored under the id."""


class SubmissionNotFoundError(Exception):
    """No submission is stored under the reference."""


class WriteUpNotFoundError(Exception):
    """No write-up is stored under the id."""


class AgentUnavailableError(Exception):
    """No run was started: the runner could not be reached or would not
    start.

    This is different from a run whose outcome is "declined". That run
    did start, and the runner refused the work.
    """


class AgentTemporarilyUnavailableError(AgentUnavailableError):
    """No run was started, but trying again later may work: for example
    a quota or a rate limit was reached, or the host was busy.

    ``retry_after`` is how many seconds to wait, if known.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class WorktreeUnavailableError(Exception):
    """A commit could not be laid out as a worktree: for example there
    was no access to the repository, the commit does not exist, or git
    is not installed."""


class ReviewIncompleteError(Exception):
    """A step of one reviewer's review failed, and trying it again will
    not help."""


class PublicationRejectedError(Exception):
    """The forge refused a write, and the same write would be refused
    again: for example the token may not set commit statuses, or the
    pull request no longer exists."""


class ReviewAgentError(Exception):
    """A reviewer's directory does not describe a reviewer, or a
    reviewer that was asked for is not installed."""
