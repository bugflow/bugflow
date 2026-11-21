"""The errors this context raises."""

from datetime import timedelta


class ForgeError(Exception):
    """A request to a forge failed."""


class ForgeRejectedError(ForgeError):
    """The forge refused, and would refuse the same request again. For
    example the pull request does not exist, or the forge does not accept
    the token."""


class ForgeRepositoryMovedError(ForgeRejectedError):
    """The forge answered a request for a repository with a redirect:
    the repository was renamed, or moved to another owner. The request
    is refused, not followed, so nothing read under the new name is
    taken as the old name's.

    ``repository`` is the name asked for and ``moved_to`` the name the
    forge gives the repository now, each as ``owner/name``.
    ``moved_to`` is None where the forge would not say, or said a name
    on another host.
    """

    def __init__(
        self, message: str, repository: str, moved_to: str | None
    ) -> None:
        super().__init__(message)
        self.repository = repository
        self.moved_to = moved_to


class ForgeUnavailableError(ForgeError):
    """The request failed for a reason that may pass: a network failure,
    an error inside the forge, or a rate limit. The same request may
    succeed later.

    ``retry_after`` is how long the forge asked the client to wait, if it
    said.
    """

    def __init__(
        self, message: str, retry_after: timedelta | None = None
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class SnapshotNotFoundError(Exception):
    """No snapshot is stored under the reference given."""


class DeliveryNotAcceptedError(Exception):
    """A delivery the poller posted was not accepted by the receiving
    server."""


class EvaluationStartError(Exception):
    """A delivery could not be passed on to start or continue an
    evaluation.

    When this is raised nothing about the delivery has been recorded, so
    if the forge sends it again it is tried again.
    """
