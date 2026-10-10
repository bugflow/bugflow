"""A doctrine already read, held in memory."""

from bugflow.method.domain.models.doctrine import Doctrine


class FixedDoctrine:
    """Implements ``DoctrineRepository`` with the doctrine it was given.

    For a doctrine parsed from a deployment, which is rows in the
    database and not a directory.
    """

    def __init__(self, doctrine: Doctrine) -> None:
        self._doctrine = doctrine

    def load(self) -> Doctrine:
        return self._doctrine
