"""Errors raised by the shared interfaces."""

from pathlib import Path


class ObjectStoreError(Exception):
    """The object store failed: it could not write an object, or could not be
    reached to read one.

    A missing object is not an error. Reading one returns None, and asking
    whether it exists returns False.
    """


class TokenRefusedError(Exception):
    """A bearer token was not accepted. The message says why. It is meant for
    the server's log and should not be shown to the caller.
    """


class SchemaError(ValueError):
    """A file parsed, and what it held was not the shape expected: a key
    missing, or a value of the wrong type.

    ``str(error)`` is ``"<path>: <message>"``. The ``path`` and the
    unprefixed ``message`` are kept as attributes so a caller can say
    the failure in its own way. A context that reads its own files
    raises a subclass, so a caller can catch exactly the failure it
    expects.
    """

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message
