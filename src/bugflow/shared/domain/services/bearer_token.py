"""Who a bearer token speaks for.

A caller is accepted on a token alone. The token is checked against
what the identity provider publishes, and nothing here is told that a
person exists before they call.
"""

from typing import Protocol

from bugflow.shared.domain.values.caller import Caller


class BearerTokenService(Protocol):
    def verify(self, token: str) -> Caller:
        """The caller ``token`` speaks for, or ``TokenRefusedError``."""
        ...
