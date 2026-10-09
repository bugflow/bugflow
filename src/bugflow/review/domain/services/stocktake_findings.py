"""The interface for reading the findings that stocktakes raised."""

from collections.abc import Sequence
from typing import Protocol

from bugflow.review.domain.models.stocktake_finding import (
    FindingDisposition,
    StocktakeFinding,
)


class StocktakeFindingsService(Protocol):
    def found(self) -> Sequence[StocktakeFinding]:
        """Return every finding a stocktake raised, oldest first."""
        ...

    def dispositions(self) -> Sequence[FindingDisposition]:
        """Return every disposition recorded for a finding, oldest
        first."""
        ...
