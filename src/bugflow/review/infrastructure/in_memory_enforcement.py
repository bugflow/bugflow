"""Which profile a repository is bound to, held in memory, for tests."""

from bugflow.review.domain.models.enforcement import (
    OBSERVE,
    EnforcementProfile,
)


class InMemoryEnforcement:
    def __init__(self) -> None:
        self._bound: dict[tuple[str, str], EnforcementProfile] = {}

    def profile_for(self, forge: str, repo: str) -> EnforcementProfile:
        return self._bound.get((forge, repo), OBSERVE)

    def bindings(self) -> dict[tuple[str, str], EnforcementProfile]:
        return dict(sorted(self._bound.items()))

    def bind(self, forge: str, repo: str, profile: EnforcementProfile) -> None:
        self._bound[(forge, repo)] = profile
