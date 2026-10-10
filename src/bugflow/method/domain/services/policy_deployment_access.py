"""The interface for asking whether a caller may deploy policies to this
server.

Whoever may deploy chooses the reviewers' instructions, because the
server cannot check what it is sent against the policy repository. So
the decision is behind an interface of its own, apart from any other
access a caller has.
"""

from typing import Protocol

from bugflow.shared.domain.values.caller import Caller


class PolicyDeploymentAccessService(Protocol):
    def may_deploy(self, caller: Caller) -> bool:
        """Whether ``caller`` may send a policy deployment, or ask for
        one to be checked."""
        ...
