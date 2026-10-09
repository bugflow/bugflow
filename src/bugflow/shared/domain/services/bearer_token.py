"""The interface for checking a bearer token.

A caller proves who they are with a token from an identity provider. The
server does not keep a list of people: anyone with a valid token is
accepted as whoever the token says they are.
"""

from typing import Protocol

from bugflow.shared.domain.values.caller import Caller


class BearerTokenService(Protocol):
    def verify(self, token: str) -> Caller:
        """Return the caller the token identifies. Raise ``TokenRefusedError``
        if the token is not accepted.
        """
        ...
