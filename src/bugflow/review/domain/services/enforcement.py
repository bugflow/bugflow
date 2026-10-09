"""The interface for asking what publishing may do for a repository."""

from typing import Protocol

from bugflow.review.domain.models.enforcement import Enforcement


class EnforcementService(Protocol):
    def enforcement_for(self, forge: str, repo: str) -> Enforcement:
        """Return what may be published for the repository, and which
        verdicts fail a commit status there."""
        ...
