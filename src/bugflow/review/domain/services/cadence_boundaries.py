"""The interface for asking where this server's own periods begin."""

from typing import Protocol

from bugflow.review.domain.models.cadence_boundary import CadenceBoundary


class CadenceBoundariesService(Protocol):
    def boundary(self, cadence: str) -> str | None:
        """Return where this server's periods of that cadence begin, or
        None where it has declared none.

        None is what refuses an allowance counted per that cadence: a
        period with no boundary is one whose start nobody stated.
        """
        ...

    def declarations(self) -> list[CadenceBoundary]:
        """Return every cadence this server has bounded, by name."""
        ...

    def declare(self, boundary: CadenceBoundary) -> None:
        """Set where this server's periods of one cadence begin."""
        ...

    def withdraw(self, cadence: str) -> None:
        """Remove one, leaving every allowance counted per that cadence
        with nothing to be counted over."""
        ...
