"""A repository as its forge lists it, and as this server knows it
(ADR 008)."""

from dataclasses import dataclass
from typing import Literal

#: What discovery found had changed about a repository.
Change = Literal["discovered", "renamed", "archived", "unarchived"]


@dataclass(frozen=True, kw_only=True)
class ListedRepository:
    """A repository its forge lists for an owner."""

    forge: str
    #: As ``owner/name``.
    name: str
    #: The forge's own id for the repository, which a rename keeps.
    forge_key: str
    archived: bool = False


@dataclass(frozen=True, kw_only=True)
class KnownRepository:
    """A repository this server holds a row for."""

    forge: str
    name: str
    #: None for a repository known from the journal and not yet listed.
    forge_key: str | None = None
    archived: bool = False


@dataclass(frozen=True, kw_only=True)
class RepositoryChange:
    """One thing discovery found had changed, and recorded."""

    forge: str
    name: str
    change: Change
    #: The name it had before, for a rename.
    was_name: str | None = None
