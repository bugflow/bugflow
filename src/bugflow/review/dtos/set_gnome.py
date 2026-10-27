"""The request and response of ``SetGnomeUseCase``."""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.gnome_setting import (
    DEFAULT_PROFILE,
    Behaviour,
)


class SetGnomeRequest(BaseModel):
    """An operator's instruction: this gnome is to behave so on this
    repository, judging by this profile."""

    model_config = ConfigDict(frozen=True)

    forge: str
    repo: str
    gnome: str
    behaviour: Behaviour
    profile: str = DEFAULT_PROFILE
    #: Who asked: an identity at the identity provider, or the program.
    set_by: str
    #: The profiles of each gnome the deployment in force holds, by
    #: agent id. A setting naming a gnome or a profile not here is
    #: refused.
    profiles: Mapping[str, tuple[str, ...]]


class SetGnomeResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    forge: str
    repo: str
    gnome: str
    behaviour: Behaviour
    profile: str
    #: False if the gnome was already so, and nothing was recorded.
    changed: bool
    #: What it was before, or None where it had no setting.
    was_behaviour: Behaviour | None = None
    was_profile: str | None = None
