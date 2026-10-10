"""The interfaces for asking what publishing may do for a repository.

``EnforcementService`` answers the use cases with one value.
``EnforcementProfileService`` answers which named profile a repository
is bound to, which is what a deployment declares and a page lists.
"""

from collections.abc import Mapping
from typing import Protocol

from bugflow.review.domain.models.enforcement import (
    Enforcement,
    EnforcementProfile,
)


class EnforcementService(Protocol):
    def enforcement_for(self, forge: str, repo: str) -> Enforcement:
        """Return what may be published for the repository, and which
        verdicts fail a commit status there."""
        ...


class EnforcementProfileService(Protocol):
    def profile_for(self, forge: str, repo: str) -> EnforcementProfile:
        """Return the profile bound to this repository, or ``observe``
        for one nobody bound."""
        ...

    def bindings(self) -> Mapping[tuple[str, str], EnforcementProfile]:
        """Return every binding, for a reader asking what this
        deployment publishes to at all."""
        ...
