"""The enforcement profile and withheld share a repository declares,
read as the one value the use cases take.

An ``EnforcementService`` over an ``EnforcementProfileService`` and a
``WithholdingService``.
"""

from bugflow.review.domain.models.enforcement import (
    Enforcement,
    EnforcementProfile,
)
from bugflow.review.domain.services.enforcement import (
    EnforcementProfileService,
)
from bugflow.review.domain.services.withholding import WithholdingService


def as_enforcement(
    profile: EnforcementProfile, withholds: float = 0.0
) -> Enforcement:
    return Enforcement(
        publishes=profile.publishes,
        fails_at=profile.fails_at,
        withholds=withholds,
    )


class DeclaredEnforcement:
    def __init__(
        self,
        profiles: EnforcementProfileService,
        withholding: WithholdingService | None = None,
    ) -> None:
        self._profiles = profiles
        # None where the deployment holds no share, and then nothing is
        # withheld anywhere, which is what a share of 0 says too.
        self._withholding = withholding

    def enforcement_for(self, forge: str, repo: str) -> Enforcement:
        return as_enforcement(
            self._profiles.profile_for(forge, repo),
            self._withholding.share_for(forge, repo)
            if self._withholding
            else 0.0,
        )
