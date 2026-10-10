"""An object store that keeps nothing, for an application with no bucket
set up.

A laptop, a test run and a server with no object store all take this.
Every call to a model is still recorded in the journal. The content of
the exchange has nowhere to go and is not kept.
"""


class NullObjectStore:
    """Implements ``ObjectStoreService`` by keeping nothing."""

    def put(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/json",
        content_encoding: str | None = "gzip",
    ) -> None:
        return None

    def get(self, key: str) -> bytes | None:
        return None

    def has(self, key: str) -> bool:
        return False

    @property
    def configured(self) -> bool:
        return False
