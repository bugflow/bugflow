"""Read what the whole server spent in a period by repository, what each
allowance has left in its current period, and the latest runs that
spent.

The figures are summed from the same rows as every other operations
page, so a repository's figure here is the one its own page shows. It
writes nothing and calls no model.
"""

from collections import defaultdict
from collections.abc import Sequence

from bugflow.review.domain.models.spend import RunCost
from bugflow.review.domain.services.spend_bindings import (
    SpendBindingsService,
)
from bugflow.review.domain.services.spend_record import SpendRecordService
from bugflow.review.dtos.read_operations_overview import (
    ReadOperationsOverviewRequest,
    ReadOperationsOverviewResponse,
    RepositorySpend,
)
from bugflow.review.dtos.read_run_operations import AllowanceCheck
from bugflow.review.usecases.allowance_checks import Window, measured
from bugflow.review.usecases.spend_rows import by_run


class ReadOperationsOverviewUseCase:
    def __init__(
        self,
        spend: SpendRecordService,
        ceilings: SpendBindingsService,
        window: Window,
    ) -> None:
        self._spend = spend
        self._ceilings = ceilings
        self._window = window

    def execute(
        self, request: ReadOperationsOverviewRequest
    ) -> ReadOperationsOverviewResponse:
        rows = self._spend.spent_by_run(request.since, request.until)
        runs = by_run(rows)
        return ReadOperationsOverviewResponse(
            since=request.since,
            until=request.until,
            repositories=_by_repository(rows),
            allowances=tuple(
                sorted(
                    (
                        measured(
                            binding, request.now, self._window, self._spend
                        )
                        for binding in self._ceilings.bindings()
                    ),
                    key=_urgency,
                )
            ),
            recent=runs[: request.recent],
            runs=len(runs),
        )


def _urgency(check: AllowanceCheck) -> tuple[int, float]:
    """Those with no room first, then those a period cannot be found
    for, then the least left, then those with no money limit and those
    measured on each run. The sort is stable, so equals keep their
    order, most specific first."""
    held = check.remaining
    if held is None:
        return (1 if check.binding.per != "event" else 4, 0.0)
    if not held.has_room:
        return (0, 0.0)
    if held.left_usd is None:
        return (3, 0.0)
    return (2, held.left_usd)


def _by_repository(rows: Sequence[RunCost]) -> tuple[RepositorySpend, ...]:
    grouped: dict[tuple[str, str], list[RunCost]] = defaultdict(list)
    for one in rows:
        grouped[(one.forge, one.repo)].append(one)
    return tuple(
        sorted(
            (
                RepositorySpend(
                    forge=forge,
                    repo=repo,
                    usd=sum(one.usd for one in held),
                    facts=sum(one.facts for one in held),
                    runs=len({(one.workflow_id, one.run_id) for one in held}),
                )
                for (forge, repo), held in grouped.items()
            ),
            key=lambda one: (-one.usd, one.forge, one.repo),
        )
    )
