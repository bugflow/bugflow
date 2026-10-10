"""The errors this context raises."""


class PolicyDeploymentError(ValueError):
    """What was sent is not a deployment, or one of its files does not
    parse. The message names every problem found."""


class PolicyDeploymentConflictError(Exception):
    """A commit already held was sent again with different content."""

    def __init__(self, repository: str, commit: str) -> None:
        super().__init__(
            f"{repository} at {commit} is already held with other content; "
            "a commit names one deployment"
        )
        self.repository = repository
        self.commit = commit


class PoliciesRefusedError(Exception):
    """A server refused the files of a deployment: they do not parse, or
    the commit is already held with other content. The message is the
    server's reason.
    """


class PolicyServerError(Exception):
    """A deployment could not be sent to a server, or the sender was not
    allowed to send it. The message says which, for the person or
    pipeline that sent it.
    """
