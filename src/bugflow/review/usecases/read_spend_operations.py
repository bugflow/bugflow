"""Read what was spent in a period by pace layer or by agent, across
every repository: for every layer or agent, or for one, with the
allowances that name it and the runs that spent it.

The same rows a repository's page sums, read for every repository, so
a layer's figure on one repository is the figure that repository's page
shows for it. It writes nothing and calls no model. Who may read it is
not decided here: the program that offers it checks that first.
"""

from collections import defaultdict
from collections.abc import Sequence

from bugflow.review.domain.models.spend import RunCost
from bugflow.review.domain.models.spend_binding import SpendScope
from bugflow.review.domain.services.spend_bindings import (
    SpendBindingsService,
)
from bugflow.review.domain.services.spend_record import SpendRecordService
from bugflow.review.dtos.read_spend_operations import (
    Dimension,
    ReadSpendOperationsRequest,
    ReadSpendOperationsResponse,
    SpendCell,
)
from bugflow.review.usecases.allowance_checks import Window, measured
from bugflow.review.usecases.spend_rows import by_run


def _named(by: Dimension, layer: str, agent_id: str) -> str:
    return layer if by == "layer" else agent_id


def _scope_names(by: Dimension, scope: SpendScope) -> str:
    return _named(by, scope.layer, scope.agent_id)


class ReadSpendOperationsUseCase:
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
        self, request: ReadSpendOperationsRequest
    ) -> ReadSpendOperationsResponse:
        by, name = request.by, request.name
        rows = [
            one
            for one in self._spend.spent_by_run(request.since, request.until)
            if name in (None, _named(by, one.layer, one.agent_id))
        ]
        # An allowance names a layer or an agent by naming it; an open
        # part covers every one and is no allowance of any one of them.
        bound = [
            binding
            for binding in self._ceilings.bindings()
            if _scope_names(by, binding.scope)
            and name in (None, _scope_names(by, binding.scope))
        ]
        return ReadSpendOperationsResponse(
            by=by,
            name=name,
            since=request.since,
            until=request.until,
            cells=_cells(rows),
            allowances=tuple(
                measured(binding, request.now, self._window, self._spend)
                for binding in bound
            ),
            runs=() if name is None else by_run(rows),
        )


def _cells(rows: Sequence[RunCost]) -> tuple[SpendCell, ...]:
    grouped: dict[tuple[str, str, str, str], list[RunCost]] = defaultdict(list)
    for one in rows:
        grouped[(one.forge, one.repo, one.layer, one.agent_id)].append(one)
    return tuple(
        sorted(
            (
                SpendCell(
                    forge=forge,
                    repo=repo,
                    layer=layer,
                    agent_id=agent_id,
                    usd=sum(one.usd for one in held),
                    facts=sum(one.facts for one in held),
                    runs=len({(one.workflow_id, one.run_id) for one in held}),
                )
                for (forge, repo, layer, agent_id), held in grouped.items()
            ),
            key=lambda cell: (
                -cell.usd,
                cell.forge,
                cell.repo,
                cell.layer,
                cell.agent_id,
            ),
        )
    )
