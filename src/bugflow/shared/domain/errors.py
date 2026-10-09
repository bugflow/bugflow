"""Errors raised by the shared interfaces."""


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
