"""The request and response of ``ReadAllowancesUseCase``."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.dtos.read_run_operations import AllowanceCheck


class ReadAllowancesRequest(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    #: The scope read: a repository or an owner, a layer and an agent,
    #: each of which may be left open.
    scope: SpendScope
    #: The moment a period allowance's current period is found for.
    now: datetime


class AppliedAllowance(BaseModel):
    """One allowance that covers every run in the scope read, beside
    what it measures, and whether the scope declares it or inherits it
    from a wider one."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    check: AllowanceCheck
    #: Declared on the scope read, and so changed there.
    own: bool


class Ceiling(BaseModel):
    """What one run in the scope is handed to spend: on each resource
    the lowest limit of the allowances per event that cover it, and the
    allowance that limit comes from. None is no limit, from nowhere."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    usd: float | None
    usd_from: SpendBinding | None
    turns: float | None
    turns_from: SpendBinding | None


class ReadAllowancesResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    scope: SpendScope
    #: Every allowance that covers the scope, most specific first.
    applied: tuple[AppliedAllowance, ...]
    #: What a run in the scope is handed, or None where no allowance per
    #: event covers it, which allows nothing.
    ceiling: Ceiling | None
