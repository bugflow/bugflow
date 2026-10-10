"""The errors this context raises."""


class PolicyDeploymentError(ValueError):
    """What was sent is not a deployment."""


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
