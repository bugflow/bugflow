"""Read what one scope is allowed: the allowances it declares, those it
inherits from the wider scopes that cover it, and what each run in it is
handed, with where each limit comes from.

An allowance per event is a ceiling handed to a run, and the run gets
the lowest of those that cover it on each resource, as a dispatch works
it out. An allowance per period measures its own scope's spend, so
each is shown with what it has left and none is folded into another.
It writes nothing and calls no model.
"""

from collections.abc import Callable, Sequence

from bugflow.review.domain.models.spend_binding import SpendBinding
from bugflow.review.domain.services.spend_bindings import (
    SpendBindingsService,
)
from bugflow.review.domain.services.spend_record import SpendRecordService
from bugflow.review.dtos.read_allowances import (
    AppliedAllowance,
    Ceiling,
    ReadAllowancesRequest,
    ReadAllowancesResponse,
)
from bugflow.review.usecases.allowance_checks import Window, measured

#: The denominator of an allowance handed to each run.
EVENT = "event"


class ReadAllowancesUseCase:
    def __init__(
        self,
        ceilings: SpendBindingsService,
        spend: SpendRecordService,
        window: Window,
    ) -> None:
        self._ceilings = ceilings
        self._spend = spend
        self._window = window

    def execute(
        self, request: ReadAllowancesRequest
    ) -> ReadAllowancesResponse:
        scope = request.scope
        covering = [
            binding
            for binding in self._ceilings.bindings()
            if binding.scope.covers(scope)
        ]
        return ReadAllowancesResponse(
            scope=scope,
            applied=tuple(
                AppliedAllowance(
                    check=measured(
                        binding, request.now, self._window, self._spend
                    ),
                    own=binding.scope == scope,
                )
                for binding in covering
            ),
            ceiling=ceiling([one for one in covering if one.per == EVENT]),
        )


def ceiling(bound: Sequence[SpendBinding]) -> Ceiling | None:
    """The lowest limit on each resource and the allowance it comes from,
    the more specific of two that set the same limit. None where nothing
    is bound, which allows nothing."""
    if not bound:
        return None
    usd_from = _lowest(bound, lambda one: one.budget.usd)
    turns_from = _lowest(bound, lambda one: one.budget.turns)
    return Ceiling(
        usd=usd_from.budget.usd if usd_from else None,
        usd_from=usd_from,
        turns=turns_from.budget.turns if turns_from else None,
        turns_from=turns_from,
    )


def _lowest(
    bound: Sequence[SpendBinding],
    limit: Callable[[SpendBinding], float | None],
) -> SpendBinding | None:
    limited = [one for one in bound if limit(one) is not None]
    if not limited:
        return None
    # Stable: of equal limits, the first, which is the most specific.
    return min(limited, key=lambda one: limit(one) or 0.0)
