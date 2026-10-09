"""What the archive refuses."""


class ArchiveRefusedError(Exception):
    """What was asked is refused, by a kind the protocol names: chain,
    sequence, encoding, identity, entry, root, absent or erased."""

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
