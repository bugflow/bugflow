"""What a repository is reviewed for, in the forge context's types.

The review context holds what each repository declared and which
policies a worker can answer. The forge context records both on an
observation, so that a policy switched off for a repository can be told
from one that ran and found nothing, and reads them through an
interface of its own. This adapter answers that interface.
"""

from collections.abc import Sequence

from bugflow.apps.worker.reviewers import policies_for
from bugflow.forge.domain.values.review_scope import ReviewScope
from bugflow.review.domain.services.review_declaration import (
    JudgedPoliciesService,
)


class DeclaredReviewScope:
    """Implements the forge context's ``ReviewScopeService`` from what
    each repository declared."""

    def __init__(
        self,
        held: Sequence[str],
        judged: JudgedPoliciesService | None,
    ) -> None:
        self._held = tuple(held)
        self._judged = judged

    def scope_for(self, forge: str, repo: str) -> ReviewScope:
        return ReviewScope(
            held=self._held,
            reviewed_for=tuple(
                policies_for(self._held, self._judged, forge, repo)
            ),
        )
