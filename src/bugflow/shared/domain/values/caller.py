"""The caller: who is making a request."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Caller:
    """The person a checked bearer token identifies.

    ``subject`` is the identity provider's id for the person. It is an
    opaque id, not a name. ``client`` is the id of the client application
    the token was issued to. ``roles`` are the roles the provider gave the
    person.
    """

    subject: str
    client: str
    roles: frozenset[str]
