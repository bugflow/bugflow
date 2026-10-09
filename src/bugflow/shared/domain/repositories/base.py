"""What a repository inherits to say which entity it is bound to."""

from typing import Protocol


class BaseRepository[Entity](Protocol):
    """Declares the one entity a repository is bound to, and nothing else.

    It has no methods: a repository loads, stores or lists as its entity
    needs, and none is CRUD.
    """
