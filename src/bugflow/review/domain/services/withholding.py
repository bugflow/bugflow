"""The interface for asking what share of each repository's warnings is
withheld."""

from typing import Protocol

from bugflow.review.domain.models.withholding import Withholding


class WithholdingService(Protocol):
    def share_for(self, forge: str, repo: str) -> float:
        """Return the share withheld on this repository, or 0 for one
        that has declared none, which is the default: a warning is
        published unless somebody decided to measure it."""
        ...

    def declarations(self) -> list[Withholding]:
        """Return every share declared, by forge and repository."""
        ...

    def declare(self, withholding: Withholding) -> None:
        """Set one repository's share, replacing what it had."""
        ...
