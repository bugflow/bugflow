"""The request and response of ``ReadRunOperationsUseCase``."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.remaining import Remaining
from bugflow.review.domain.models.spend import CostFact
from bugflow.review.domain.models.spend_binding import SpendBinding


class ReadRunOperationsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str
    run_id: str
    #: The moment a period allowance's current period is found for.
    now: datetime


class AllowanceCheck(BaseModel):
    """One allowance that covers the run, beside what it measures.

    ``remaining`` is None where the allowance's period cannot be found,
    and ``unmeasured`` then says why: a ceiling nobody can count is shown
    as such, not left out.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    binding: SpendBinding
    remaining: Remaining | None = None
    unmeasured: str = ""


class RunActivity(BaseModel):
    """One entry the run recorded, as a page lists it."""

    model_config = ConfigDict(frozen=True)

    event_id: str
    occurred_at: datetime
    event_type: str
    #: The agent the entry names, or empty.
    agent_id: str
    #: The pull request it is about, or None.
    pr_number: int | None = None


class ReadRunOperationsResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    workflow_id: str
    run_id: str
    forge: str
    repo: str
    #: Every costed fact, oldest first.
    costs: tuple[CostFact, ...]
    #: Every allowance that covers the run, most specific first.
    allowances: tuple[AllowanceCheck, ...]
    #: Every entry the run recorded, oldest first.
    activity: tuple[RunActivity, ...]

    @property
    def spent_usd(self) -> float:
        return sum(one.usd for one in self.costs)
