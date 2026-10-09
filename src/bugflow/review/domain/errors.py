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
