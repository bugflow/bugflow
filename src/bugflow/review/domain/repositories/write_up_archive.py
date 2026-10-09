"""The interface for storing a checkout agent's write-up.

The journal records that a run happened and what it cost. The write-up
is a document, and is stored apart from the journal.
"""

from typing import Protocol

from bugflow.review.domain.models.write_up import WriteUp
from bugflow.shared.domain.repositories.base import BaseRepository


class WriteUpArchiveRepository(BaseRepository[WriteUp], Protocol):
    def put(self, write_up: WriteUp) -> str:
        """Store a write-up and return its id. Storing a write-up for
        the same workflow run and agent again keeps what is already
        there and returns the same id."""
        ...

    def get(self, write_up_id: str) -> WriteUp:
        """Return the write-up. Raises ``WriteUpNotFoundError`` if there
        is none under the id."""
        ...
