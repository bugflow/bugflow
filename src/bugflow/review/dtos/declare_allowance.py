"""The request and response of ``DeclareAllowanceUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.spend_binding import SpendScope
from bugflow.shared.domain.values.budget import Budget


class DeclareAllowanceRequest(BaseModel):
    """An operator's instruction: this scope is allowed so much per this
    cadence, or, with no budget, is no longer allowed anything per it."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    scope: SpendScope
    #: The cadence the allowance is counted per. Which names are
    #: cadences is the method's; the program that asks checks it.
    per: str
    #: What the allowance holds, or None to revoke it. Revoking is not
    #: allowing zero: it leaves the scope to the wider allowances that
    #: cover it.
    budget: Budget | None
    #: Who asked: an identity at the identity provider, or the program.
    declared_by: str


class DeclareAllowanceResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    scope: SpendScope
    per: str
    #: What the scope holds for the cadence now, and held before.
    held: Budget | None
    was: Budget | None

    @property
    def changed(self) -> bool:
        return self.held != self.was
