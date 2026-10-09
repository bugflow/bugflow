"""The budget: what a run may spend, and how several limits combine."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True, kw_only=True)
class Budget:
    """What one run may spend before it is stopped.

    The amounts are in the units people use when they set a limit:
    dollars, and turns. An adapter that needs another unit, such as
    cents, converts for itself.

    Each field is a limit. None means no limit on that resource. "No
    limit" is written as None and never as a very large number, so that
    it can be told apart from a limit somebody chose.

    The defaults, five dollars and sixty turns, are what a budget
    recorded with no figures is read as.
    """

    #: The most money, in dollars. None for no limit.
    usd: float | None = 5.0
    #: The most turns the runner may take. None for no limit. A run
    #: that is stuck in a loop usually reaches this before the money.
    turns: float | None = 60.0


def allowance(
    bound: Iterable[Budget], declared: Budget | None
) -> Budget | None:
    """Work out what a run may spend. Returns None if it may spend
    nothing.

    ``bound`` is every budget that somebody has granted and that
    applies to this run: for example one for the repository and one for
    the reviewer. ``declared`` is what the work itself says it should
    cost, if it says.

    The rules:

    - If nothing was granted, the run may spend nothing. Nobody having
      set a limit is not the same as somebody having allowed the usual
      amount.
    - If several budgets were granted, all of them apply. On each
      resource the run gets the lowest.
    - A declared figure can only lower the result. It grants nothing by
      itself.
    """
    allowed = list(bound)
    if not allowed:
        return None
    figures = allowed + ([declared] if declared else [])
    return Budget(
        usd=_lowest(one.usd for one in figures),
        turns=_lowest(one.turns for one in figures),
    )


def _lowest(figures: Iterable[float | None]) -> float | None:
    """The lowest of the limits, ignoring any that are None. If all are
    None there is no limit, and the result is None."""
    named = [one for one in figures if one is not None]
    return min(named) if named else None


#: How many calendar months one period of each span has.
_MONTHS = {"month": 1, "quarter": 3, "year": 12}

#: How many days one period of each span has.
_DAYS = {"day": 1, "week": 7, "fortnight": 14}


def _add_months(at: datetime, months: int) -> datetime:
    total = at.month - 1 + months
    year, month = at.year + total // 12, total % 12 + 1
    return at.replace(year=year, month=month)


def period(
    span: str, begins: datetime, now: datetime
) -> tuple[datetime, datetime] | None:
    """Find the period that contains ``now``, as (start, end).

    Periods are ``span`` long: "day", "week", "fortnight", "month",
    "quarter" or "year". They are counted from ``begins``, which is the
    start of one period. The caller says where periods begin, because
    that differs: a week may run from Monday or from Wednesday.

    ``begins`` may be later than ``now``. The periods are then counted
    backwards from it.

    Returns None when ``span`` is empty, which means the budget is for a
    single run and not for a period of time. Raises ``ValueError`` for
    any other span.
    """
    if not span:
        return None
    if span in _DAYS:
        length = timedelta(days=_DAYS[span])
        elapsed = (now - begins) // length
        start = begins + elapsed * length
        return start, start + length
    if span not in _MONTHS:
        raise ValueError(f"{span!r} is no span a period can be counted in")
    months = _MONTHS[span]
    # Months are stepped one period at a time, because they are not all
    # the same length and cannot be divided like days.
    start = begins
    while _add_months(start, months) <= now:
        start = _add_months(start, months)
    while start > now:
        start = _add_months(start, -months)
    return start, _add_months(start, months)
