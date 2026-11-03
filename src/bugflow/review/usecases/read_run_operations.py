"""Read what one run spent, the allowances that cover it, and what it
recorded.

It writes nothing and calls no model. Who may read it is not decided
here: the program that offers it checks that first.
"""

from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol

from bugflow.review.domain.errors import RunNotFoundError
from bugflow.review.domain.models.remaining import Remaining
from bugflow.review.domain.models.review_entry import ReviewEntry
from bugflow.review.domain.models.spend import CostFact, Spent
from bugflow.review.domain.models.spend_binding import SpendBinding
from bugflow.review.domain.services.spend_bindings import (
    SpendBindingsService,
)
from bugflow.review.domain.services.spend_record import SpendRecordService
from bugflow.review.dtos.read_run_operations import (
    AllowanceCheck,
    ReadRunOperationsRequest,
    ReadRunOperationsResponse,
    RunActivity,
)
from bugflow.shared.domain.values.correlation import Correlation

#: The period of an allowance that contains a moment, None for an
#: allowance per run, or ``ValueError`` where nothing says where its
#: periods begin.
Window = Callable[[SpendBinding, datetime], tuple[datetime, datetime] | None]


class RunEntries(Protocol):
    def entries_for_run(self, correlation: Correlation) -> list[ReviewEntry]:
        """Return every entry one workflow run recorded, oldest first."""
        ...


class ReadRunOperationsUseCase:
    def __init__(
        self,
        journal: RunEntries,
        spend: SpendRecordService,
        ceilings: SpendBindingsService,
        window: Window,
    ) -> None:
        self._journal = journal
        self._spend = spend
        self._ceilings = ceilings
        self._window = window

    def execute(
        self, request: ReadRunOperationsRequest
    ) -> ReadRunOperationsResponse:
        """Raises ``RunNotFoundError`` when the run recorded nothing."""
        entries = self._journal.entries_for_run(
            Correlation(workflow_id=request.workflow_id, run_id=request.run_id)
        )
        if not entries:
            raise RunNotFoundError(
                f"no run {request.run_id} of {request.workflow_id}"
            )
        forge, repo = entries[0].forge, entries[0].repo
        costs = tuple(
            self._spend.costs_in_run(request.workflow_id, request.run_id)
        )
        return ReadRunOperationsResponse(
            workflow_id=request.workflow_id,
            run_id=request.run_id,
            forge=forge,
            repo=repo,
            costs=costs,
            allowances=self._checks(forge, repo, costs, request.now),
            activity=tuple(
                RunActivity(
                    event_id=str(one.event_id),
                    occurred_at=one.occurred_at,
                    event_type=one.event_type,
                    agent_id=one.agent_id or "",
                    pr_number=one.pr_number,
                )
                for one in entries
            ),
        )

    def _checks(
        self,
        forge: str,
        repo: str,
        costs: Sequence[CostFact],
        now: datetime,
    ) -> tuple[AllowanceCheck, ...]:
        """Every allowance that covers some part of the run, once each.

        A run is covered on each layer and agent its facts name, and on
        neither, since judging names no agent.
        """
        seen: dict[tuple[object, str], SpendBinding] = {}
        for layer, agent_id in {("", "")} | {
            (one.layer, one.agent_id) for one in costs
        }:
            for binding in self._ceilings.binding_for(
                forge, repo, layer, agent_id
            ):
                seen.setdefault((binding.scope, binding.per), binding)
        bindings = sorted(
            seen.values(), key=lambda one: one.scope.parts, reverse=True
        )
        return tuple(
            self._check(binding, forge, repo, costs, now)
            for binding in bindings
        )

    def _check(
        self,
        binding: SpendBinding,
        forge: str,
        repo: str,
        costs: Sequence[CostFact],
        now: datetime,
    ) -> AllowanceCheck:
        try:
            window = self._window(binding, now)
        except ValueError as unbounded:
            return AllowanceCheck(binding=binding, unmeasured=str(unbounded))
        scope = binding.scope
        if window is not None:
            spent = self._spend.spent(
                *window,
                forge=scope.forge,
                repo=scope.repo,
                layer=scope.layer,
                agent_id=scope.agent_id,
                owner=scope.owner,
            )
            return AllowanceCheck(
                binding=binding,
                remaining=Remaining(binding=binding, spent=spent),
            )
        # An allowance per run holds this run: what it counts is what
        # the run's own facts in its scope cost, over the run.
        covered = [
            one
            for one in costs
            if scope.layer in ("", one.layer)
            and scope.agent_id in ("", one.agent_id)
        ]
        if not covered:
            return AllowanceCheck(
                binding=binding,
                unmeasured="the run recorded no cost this allowance covers",
            )
        return AllowanceCheck(
            binding=binding,
            remaining=Remaining(
                binding=binding,
                spent=Spent(
                    forge=forge,
                    repo=repo,
                    layer=scope.layer,
                    agent_id=scope.agent_id,
                    since=min(one.occurred_at for one in covered),
                    until=max(one.occurred_at for one in covered),
                    usd=sum(one.usd for one in covered),
                    facts=len(covered),
                ),
            ),
        )
