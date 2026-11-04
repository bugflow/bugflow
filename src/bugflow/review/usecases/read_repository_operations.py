"""Read what one repository is set to do and may spend, what it spent
in a period by layer and agent, and the runs that spent it.

The spend rows and the runs are read from the same rows, one for each
run, layer, agent and kind of fact, so a row's total is the sum of the
runs listed for it. It writes nothing and calls no model. Who may read
it is not decided here: the program that offers it checks that first.
"""

from collections import defaultdict
from collections.abc import Sequence

from bugflow.review.domain.models.spend import RunCost
from bugflow.review.domain.services.gnome_settings import (
    GnomeSettingsService,
)
from bugflow.review.domain.services.spend_bindings import (
    SpendBindingsService,
)
from bugflow.review.domain.services.spend_record import SpendRecordService
from bugflow.review.dtos.read_repository_operations import (
    ReadRepositoryOperationsRequest,
    ReadRepositoryOperationsResponse,
    SpendRow,
)
from bugflow.review.usecases.allowance_checks import Window, measured
from bugflow.review.usecases.spend_rows import by_run


class ReadRepositoryOperationsUseCase:
    def __init__(
        self,
        settings: GnomeSettingsService,
        spend: SpendRecordService,
        ceilings: SpendBindingsService,
        window: Window,
    ) -> None:
        self._settings = settings
        self._spend = spend
        self._ceilings = ceilings
        self._window = window

    def execute(
        self, request: ReadRepositoryOperationsRequest
    ) -> ReadRepositoryOperationsResponse:
        rows = self._spend.spent_by_run(
            request.since,
            request.until,
            forge=request.forge,
            repo=request.repo,
        )
        listed = [
            one
            for one in rows
            if request.layer in (None, one.layer)
            and request.agent_id in (None, one.agent_id)
        ]
        return ReadRepositoryOperationsResponse(
            forge=request.forge,
            repo=request.repo,
            since=request.since,
            until=request.until,
            settings=tuple(
                self._settings.settings_of(request.forge, request.repo)
            ),
            allowances=tuple(
                measured(binding, request.now, self._window, self._spend)
                for binding in self._ceilings.bindings()
                if binding.scope.reaches(request.forge, request.repo)
            ),
            spend=_by_layer_and_agent(rows),
            layer=request.layer,
            agent_id=request.agent_id,
            runs=by_run(listed),
        )


def _by_layer_and_agent(rows: Sequence[RunCost]) -> tuple[SpendRow, ...]:
    grouped: dict[tuple[str, str], list[RunCost]] = defaultdict(list)
    for one in rows:
        grouped[(one.layer, one.agent_id)].append(one)
    return tuple(
        sorted(
            (
                SpendRow(
                    layer=layer,
                    agent_id=agent_id,
                    usd=sum(one.usd for one in held),
                    facts=sum(one.facts for one in held),
                    runs=len({(one.workflow_id, one.run_id) for one in held}),
                )
                for (layer, agent_id), held in grouped.items()
            ),
            key=lambda row: (-row.usd, row.layer, row.agent_id),
        )
    )
