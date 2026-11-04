"""The request and response of ``ReadSpendOperationsUseCase``."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from bugflow.review.dtos.read_repository_operations import RunRow
from bugflow.review.dtos.read_run_operations import AllowanceCheck

#: What the spend is read by: the pace layer its facts name, or the
#: agent.
Dimension = Literal["layer", "agent"]


class ReadSpendOperationsRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    by: Dimension
    #: The layer or the agent read, where empty names the facts that
    #: name none. None reads every one of them.
    name: str | None = None
    #: The period the spend and the runs are read over.
    since: datetime
    until: datetime
    #: The moment a period allowance's current period is found for.
    now: datetime

    @model_validator(mode="after")
    def _a_period_ends_after_it_begins(self) -> "ReadSpendOperationsRequest":
        if self.until <= self.since:
            raise ValueError("a period ends after it begins")
        return self


class SpendCell(BaseModel):
    """What one layer and agent spent on one repository in the period.

    Empty names the facts that name no layer or no agent: a judge's
    calls name neither.
    """

    model_config = ConfigDict(frozen=True)

    forge: str
    repo: str
    layer: str
    agent_id: str
    usd: float
    facts: int
    #: How many runs the figure is made of.
    runs: int


class ReadSpendOperationsResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    by: Dimension
    name: str | None
    since: datetime
    until: datetime
    #: What each repository, layer and agent spent, most first: of the
    #: layer or agent read, or of every one.
    cells: tuple[SpendCell, ...]
    #: Every allowance whose scope names the layer or agent read, or
    #: names any layer or agent where none is read, most specific
    #: first, each measured over its current period.
    allowances: tuple[AllowanceCheck, ...]
    #: The runs the cells are made of, latest first. Listed only where a
    #: layer or agent is read: every run in a period is the overview's.
    runs: tuple[RunRow, ...]

    @property
    def spent_usd(self) -> float:
        return sum(one.usd for one in self.cells)
