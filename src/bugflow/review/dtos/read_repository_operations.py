"""The request and response of ``ReadRepositoryOperationsUseCase``."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, model_validator

from bugflow.review.domain.models.gnome_setting import GnomeSetting
from bugflow.review.dtos.read_run_operations import AllowanceCheck


class ReadRepositoryOperationsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    forge: str
    repo: str
    #: The period the spend and the runs are read over.
    since: datetime
    until: datetime
    #: The moment a period allowance's current period is found for.
    now: datetime
    #: The spend row whose runs are listed: a layer and an agent, where
    #: empty names the facts that name none. None lists every run.
    layer: str | None = None
    agent_id: str | None = None

    @model_validator(mode="after")
    def _a_period_ends_after_it_begins(
        self,
    ) -> "ReadRepositoryOperationsRequest":
        if self.until <= self.since:
            raise ValueError("a period ends after it begins")
        return self


class SpendRow(BaseModel):
    """What one layer and agent spent on the repository in the period.

    Empty names the facts that name no layer or no agent: a judge's
    calls name neither.
    """

    model_config = ConfigDict(frozen=True)

    layer: str
    agent_id: str
    usd: float
    facts: int
    #: How many runs the figure is made of.
    runs: int


class RunRow(BaseModel):
    """What one run spent in the period, within the spend row it is
    listed for."""

    model_config = ConfigDict(frozen=True)

    workflow_id: str
    run_id: str
    forge: str
    repo: str
    #: When the earliest and the latest of its facts were recorded.
    first: datetime
    last: datetime
    usd: float
    facts: int


class ReadRepositoryOperationsResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    forge: str
    repo: str
    since: datetime
    until: datetime
    #: What each gnome does on the repository, by gnome.
    settings: tuple[GnomeSetting, ...]
    #: Every allowance that covers some run on the repository, most
    #: specific first, each measured over its current period.
    allowances: tuple[AllowanceCheck, ...]
    #: What each layer and agent spent, most first.
    spend: tuple[SpendRow, ...]
    #: The spend row the runs are listed for, as the request named it.
    layer: str | None
    agent_id: str | None
    #: The runs that make up that row, or every run, latest first.
    runs: tuple[RunRow, ...]

    @property
    def spent_usd(self) -> float:
        return sum(one.usd for one in self.spend)
