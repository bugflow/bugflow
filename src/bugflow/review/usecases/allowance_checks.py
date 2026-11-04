"""Measuring an allowance over its current period, for the pages that
show what a scope has left."""

from collections.abc import Callable
from datetime import datetime

from bugflow.review.domain.models.remaining import Remaining
from bugflow.review.domain.models.spend_binding import SpendBinding
from bugflow.review.domain.services.spend_record import SpendRecordService
from bugflow.review.dtos.read_run_operations import AllowanceCheck

#: The period of an allowance that contains a moment, None for an
#: allowance per run, or ``ValueError`` where nothing says where its
#: periods begin.
Window = Callable[[SpendBinding, datetime], tuple[datetime, datetime] | None]


def in_period(
    binding: SpendBinding,
    now: datetime,
    window: Window,
    spend: SpendRecordService,
) -> AllowanceCheck | None:
    """The allowance beside what its scope spent in the period that
    holds ``now``, or None for an allowance per run, which a period
    does not measure."""
    try:
        period = window(binding, now)
    except ValueError as unbounded:
        return AllowanceCheck(binding=binding, unmeasured=str(unbounded))
    if period is None:
        return None
    scope = binding.scope
    spent = spend.spent(
        *period,
        forge=scope.forge,
        repo=scope.repo,
        layer=scope.layer,
        agent_id=scope.agent_id,
        owner=scope.owner,
    )
    return AllowanceCheck(
        binding=binding, remaining=Remaining(binding=binding, spent=spent)
    )


#: Why an allowance per run is not measured where many runs are read.
PER_RUN = "an allowance per run is measured on each run"


def measured(
    binding: SpendBinding,
    now: datetime,
    window: Window,
    spend: SpendRecordService,
) -> AllowanceCheck:
    """The allowance beside what its scope spent in its current period,
    or, for an allowance per run, said to be measured on each run."""
    return in_period(binding, now, window, spend) or AllowanceCheck(
        binding=binding, unmeasured=PER_RUN
    )
