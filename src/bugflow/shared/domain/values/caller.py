"""Who is asking."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Caller:
    """Whoever a verified bearer token speaks for.

    ``subject`` is the identity provider's identifier for the person,
    never a name. ``client`` is the client the token was issued to,
    which says how the call arrived. ``roles`` are the roles the provider
    granted, as its token carries them.
    """

    subject: str
    client: str
    roles: frozenset[str]
