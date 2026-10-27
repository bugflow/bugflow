"""What one gnome does on one repository (ADR 008).

A repository is set for each gnome, a reviewer by its agent id, by two
values. The behaviour says what the gnome may do there. The profile
names which of the gnome's policies it judges there, one of the
profiles the deployment in force holds for it.

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

_PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def at_least(behaviour: Behaviour, floor: Behaviour) -> bool:
    """Whether the behaviour does everything ``floor`` does."""
    return BEHAVIOURS.index(behaviour) >= BEHAVIOURS.index(floor)


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
