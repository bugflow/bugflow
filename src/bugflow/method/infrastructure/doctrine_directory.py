"""Read a doctrine from a directory of Markdown files.

The files are read in filename order and joined, so clauses grow by
topic without one long file. The order is part of the text the judge is
given, and so part of the doctrine's version.
"""

from pathlib import Path

from bugflow.method.domain.errors import DoctrineNotFoundError
from bugflow.method.domain.models.doctrine import Doctrine


def joined(texts: list[str]) -> Doctrine:
    """The doctrine the texts make, in the order given: each stripped
    of leading and trailing newlines, joined by one newline, with one
    newline at the end. A deployment's doctrine files are joined the
    same way, so the two give one version for one text."""
    return Doctrine(text="\n".join(t.strip("\n") for t in texts) + "\n")


class DirectoryDoctrine:
    """Implements ``DoctrineRepository`` over a directory."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> Doctrine:
        """Raises ``DoctrineNotFoundError`` if the directory holds no
        Markdown file."""
        files = sorted(self._path.glob("*.md"))
        if not files:
            raise DoctrineNotFoundError(
                f"no doctrine under {self._path}: it holds no .md file"
            )
        return joined([path.read_text() for path in files])
