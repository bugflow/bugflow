"""What one gnome does on one repository (ADR 008).

A repository is set for each gnome, a reviewer by its agent id, by two
values. The behaviour says what the gnome may do there. The profile
names which of the gnome's policies it judges there, one of the
profiles the deployment in force holds for it.

A setting is one tenant's (ADR 012): the tenant whose deployment in
force holds the gnome, and whose worker reads it. Two tenants may hold
a gnome of one id, and each has its own setting of it on a repository.
A server with one tenant names none, and its settings are
``default``'s.

A repository and gnome with no setting are ``off``, so a repository
nobody decided about costs nothing.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Behaviour = Literal["off", "observe", "advise", "gate"]

#: The behaviours, each doing what the one before it does and more.
BEHAVIOURS: tuple[Behaviour, ...] = ("off", "observe", "advise", "gate")

#: The profile a setting names when nobody chose one.
DEFAULT_PROFILE = "default"

#: The tenant of a server that names none. The method context names
#: the same tenant for a deployment; this context does not import it.
DEFAULT_TENANT = "default"

_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def at_least(behaviour: Behaviour, floor: Behaviour) -> bool:
    """Whether the behaviour does everything ``floor`` does."""
    return BEHAVIOURS.index(behaviour) >= BEHAVIOURS.index(floor)


def qualified(tenant: str, gnome: str) -> str:
    """One tenant's gnome, named so that no other tenant's gnome of the
    same id is named alike: the gnome's id for the default tenant, and
    ``tenant/gnome`` for any other. A tenant's name holds no slash, so
    the name reads back as the tenant up to the first slash and the
    gnome after it. It names a column of the settings page and a commit
    status at the forge."""
    return gnome if tenant == DEFAULT_TENANT else f"{tenant}/{gnome}"


@dataclass(frozen=True, kw_only=True)
class GnomeSetting:
    """One gnome's setting on one repository."""

    forge: str
    #: As ``owner/name``.
    repo: str
    #: The reviewer's agent id.
    gnome: str
    behaviour: Behaviour
    profile: str = DEFAULT_PROFILE
    #: Whose gnome it is: the tenant whose deployment in force holds it.
    tenant: str = DEFAULT_TENANT
    #: Who made the setting: a person's identity at the identity
    #: provider, or the program that made it.
    set_by: str = ""
    set_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.behaviour not in BEHAVIOURS:
            raise ValueError(
                f"{self.behaviour!r} is no behaviour; name one of "
                f"{', '.join(BEHAVIOURS)}"
            )
        if not _PROFILE_NAME.match(self.profile):
            raise ValueError(
                f"{self.profile!r} is no profile's name: a profile's name "
                "is lower case letters, digits and hyphens"
            )
        if not self.gnome:
            raise ValueError("a setting names its gnome")
        if not self.tenant:
            raise ValueError("a setting names its gnome's tenant")

    @property
    def qualified(self) -> str:
        """The gnome's name among every tenant's gnomes."""
        return qualified(self.tenant, self.gnome)

    @property
    def judges(self) -> bool:
        """Whether the gnome judges the repository at all."""
        return at_least(self.behaviour, "observe")

    @property
    def publishes(self) -> bool:
        """Whether the gnome's comment and status reach the forge."""
        return at_least(self.behaviour, "advise")

    @property
    def gates(self) -> bool:
        """Whether the gnome's status fails on a ``fail`` verdict, and its
        verdict decides the label."""
        return self.behaviour == "gate"
