"""The errors this context raises."""


class AgentUnavailableError(Exception):
    """No run was started: the runner could not be reached or would not
    start.

    This is different from a run whose outcome is "declined". That run
    did start, and the runner refused the work. A caller needs to tell
    the two apart, because one is an outage and the other is an answer.
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


class WriteUpNotKeptError(Exception):
    """A write-up could not be stored. Nothing may be recorded that
    refers to it. Storing it can be tried again."""
