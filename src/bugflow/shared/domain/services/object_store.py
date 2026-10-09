"""The interface for an object store: a place that keeps bytes under a key,
such as an S3 bucket.

Code that uses it does not know which store is behind it. That is chosen
when an application is set up.
"""

from typing import Protocol


class ObjectStoreService(Protocol):
    """Keeps bytes under a key."""

    def put(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/json",
        content_encoding: str | None = "gzip",
    ) -> None:
        """Store ``body`` under ``key``. A key is written once and never
        overwritten. Raises ``ObjectStoreError`` if the store cannot be
        written to.
        """
        ...

    def get(self, key: str) -> bytes | None:
        """Return the bytes stored under ``key``, or None if there are none.
        Raises ``ObjectStoreError`` if the store cannot be read.
        """
        ...

    def has(self, key: str) -> bool:
        """Whether anything is stored under ``key``, without fetching it."""
        ...

    @property
    def configured(self) -> bool:
        """False for a stand-in that stores nothing, used when an application
        has no store set up. True otherwise.
        """
        ...
