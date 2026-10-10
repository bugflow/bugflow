"""What a server answers when a deployment is sent to it."""

from dataclasses import dataclass
from typing import Literal

#: ``deployed``: the deployment was stored and put in force.
#: ``already_in_force``: it was in force already, and nothing changed.
#: ``checked``: the files parse, and nothing was stored.
Outcome = Literal["deployed", "already_in_force", "checked"]


@dataclass(frozen=True, kw_only=True)
class InForce:
    """The deployment a server reviews with."""

    repository: str
    commit: str
    content_hash: str


@dataclass(frozen=True, kw_only=True)
class ServerAnswer:
    outcome: Outcome
    #: The hash the server computed from the files it was sent.
    content_hash: str
    #: The deployment in force after the call, or None if the server has
    #: never been sent one.
    in_force: InForce | None
