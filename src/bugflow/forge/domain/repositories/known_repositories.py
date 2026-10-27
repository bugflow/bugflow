"""Where the repositories this server knows of are kept."""

from collections.abc import Collection
from typing import Protocol

from bugflow.forge.domain.models.forge_repository import (
    KnownRepository,
    ListedRepository,
)


class KnownRepositoriesRepository(Protocol):
    def known(
        self, forge: str, owner: str, forge_keys: Collection[str] = ()
    ) -> list[KnownRepository]:
        """Every repository of the owner this server holds a row for,
        and any of the forge's with one of ``forge_keys``, which may have
        moved from another owner."""
        ...

    def keep(self, listed: ListedRepository) -> None:
        """Hold the repository as listed: its name, its forge's key and
        whether it is archived. A row with the same key is renamed to the
        listed name, unless another row holds that name, which then takes
        the key; else a row with the listed name takes the key; else a
        row is made."""
        ...
