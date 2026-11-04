"""The request and response of ``ReadOperationsOverviewUseCase``."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bugflow.review.dtos.read_repository_operations import RunRow
from bugflow.review.dtos.read_run_operations import AllowanceCheck


class ReadOperationsOverviewRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: The period the spend and the runs are read over.
    since: datetime
    until: datetime
    #: The moment each allowance's current period is found for.
    now: datetime
    #: How many of the latest runs are listed.
    recent: int = Field(default=20, ge=1, le=200)

    @model_validator(mode="after")
    def _a_period_ends_after_it_begins(
        self,
    ) -> "ReadOperationsOverviewRequest":
        if self.until <= self.since:
            raise ValueError("a period ends after it begins")
        return self


class RepositorySpend(BaseModel):
    """What one repository spent in the period."""

    model_config = ConfigDict(frozen=True)

    forge: str
    repo: str
    usd: float
    facts: int
    runs: int


class ReadOperationsOverviewResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    since: datetime
    until: datetime
    #: What each repository spent, most first.
    repositories: tuple[RepositorySpend, ...]
    #: Every allowance, measured over its current period: those with no
    #: room and those that cannot be measured first, then the least
    #: left. An allowance per run is measured on each run.
    allowances: tuple[AllowanceCheck, ...]
    #: The latest runs that spent in the period, latest first.
    recent: tuple[RunRow, ...]
    #: How many runs spent in the period, of which ``recent`` are the
    #: latest.
    runs: int

    @property
    def spent_usd(self) -> float:
        return sum(one.usd for one in self.repositories)
