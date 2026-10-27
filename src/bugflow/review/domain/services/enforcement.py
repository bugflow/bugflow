"""The interface for asking what publishing may do on a repository."""

from typing import Protocol

from bugflow.review.domain.models.enforcement import Enforcement


class EnforcementService(Protocol):
    def enforcement_for(self, forge: str, repo: str) -> Enforcement:
        """Return which gnomes publish and gate on the repository, and
        the share of its warnings withheld."""
        ...
