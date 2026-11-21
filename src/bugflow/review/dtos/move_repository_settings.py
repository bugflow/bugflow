"""The request and response of ``MoveRepositorySettingsUseCase``."""

from pydantic import BaseModel, ConfigDict


class MoveRepositorySettingsRequest(BaseModel):
    """A repository on one forge, renamed from ``repo`` to ``to``."""

    model_config = ConfigDict(frozen=True)

    forge: str
    #: The old name, as ``owner/name``.
    repo: str
    #: The new name, as ``owner/name``.
    to: str
    #: Who moved them: an identity at the identity provider, or the
    #: program.
    set_by: str


class MoveRepositorySettingsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: The gnomes now set on the new name as they were on the old, each
    #: by its qualified name.
    moved: tuple[str, ...]
    #: The gnomes the new name already had a setting for, which it
    #: keeps. Each is off on the old name all the same.
    kept: tuple[str, ...]
    #: The layers whose boundary the new name now has from the old.
    boundaries: tuple[str, ...]
    #: Whether the new name now withholds the old name's share.
    withholding: bool
