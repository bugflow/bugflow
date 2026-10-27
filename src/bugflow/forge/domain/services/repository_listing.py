"""The interface for asking a forge which repositories an owner has."""

from typing import Protocol

from bugflow.forge.domain.models.forge_repository import ListedRepository


class RepositoryListingService(Protocol):
    def repositories_of(self, owner: str) -> list[ListedRepository]:
        """Every repository of the owner this server's token can see,
        archived ones included. May raise ``ForgeError``."""
        ...
