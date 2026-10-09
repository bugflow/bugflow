"""The archive's error."""


class ArchiveRefusedError(Exception):
    """The archive refuses a request.

    ``kind`` is one of the refusal kinds the remote archive protocol
    defines, such as ``access``, ``absent``, ``chain`` or ``entry``. The
    application turns the kind into an HTTP status.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
