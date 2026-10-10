"""The interface for asking where each repository's periods begin.

One row per repository per layer, and a listing of them all, so a page
can show what was declared.
"""

from typing import Protocol

from bugflow.review.domain.models.layer_boundary import LayerBoundary


class LayerBoundariesService(Protocol):
    def boundary(self, forge: str, repo: str, layer: str) -> str | None:
        """Return that repository's boundary on that layer, or None
        where it has declared none.

        None is not a default to fall back from. It is the state an
        application refuses at startup, because a period with no
        boundary is one whose start nobody stated.
        """
        ...

    def declarations(self) -> list[LayerBoundary]:
        """Return every boundary declared, by forge, repository and
        layer."""
        ...

    def declare(self, boundary: LayerBoundary) -> None:
        """Set one repository's boundary on one layer, replacing what it
        had. One layer at a time, because a caller holding a stale set
        would otherwise move a boundary it never meant to name."""
        ...

    def withdraw(self, forge: str, repo: str, layer: str) -> None:
        """Remove one boundary. A repository still watched on that layer
        stops the worker at its next start, which is the point."""
        ...
