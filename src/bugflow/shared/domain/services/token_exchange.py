"""Exchange a verified caller's token for one addressed to another service."""

from typing import Protocol


class TokenExchangeService(Protocol):
    def exchange(self, token: str) -> str:
        """Return the exchanged token or raise TokenRefusedError."""
        ...
