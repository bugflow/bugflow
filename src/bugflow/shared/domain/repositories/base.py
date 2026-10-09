"""The base class for repository interfaces."""

from typing import Protocol


class BaseRepository[Entity](Protocol):
    """A repository interface inherits from this to say which entity it
    stores: ``class BindingRepository(BaseRepository[ArchiveBinding])``.

    It has no methods. Each repository declares the methods its entity
    needs.
    """
