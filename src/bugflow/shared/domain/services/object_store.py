"""Where bytes are kept by a key.

The interface knows nothing about which store: a hosted S3 service on
one deployment and a self-hosted one on another are the same code, and
which one is a fact about a deployment.
"""

from typing import Protocol


class ObjectStoreService(Protocol):
    def put(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/json",
        content_encoding: str | None = "gzip",
    ) -> None:
        """Write the object, once. Keys are never reused or overwritten.
        A store that cannot be written raises ``ObjectStoreError``."""
        ...

    def get(self, key: str) -> bytes | None:
        """The object's bytes as they were written, or None if there is no
        such object. A store that cannot be read raises
        ``ObjectStoreError``."""
        ...

    def has(self, key: str) -> bool:
        """Whether there is such an object, without reading it."""
        ...

    @property
    def configured(self) -> bool:
        """Whether anything is actually stored. An application given no
        store runs with one that keeps nothing, and says so here."""
        ...
