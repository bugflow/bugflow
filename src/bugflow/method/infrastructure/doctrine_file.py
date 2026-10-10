"""Read a doctrine from one file."""

from pathlib import Path

from bugflow.method.domain.models.doctrine import Doctrine


class FileDoctrine:
    """Implements ``DoctrineRepository`` over one file."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> Doctrine:
        return Doctrine(text=self._path.read_text())
