"""What this deployment spent, kept in memory, for tests."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from bugflow.review.domain.models.spend import (
    RunCost,
    RunSpend,
    SpendKind,
    Spent,
)
from bugflow.review.domain.models.spend_binding import owner_of


@dataclass(frozen=True, kw_only=True)
class RecordedCost:
    """One costed fact, with the run that recorded it and its kind."""

    workflow_id: str = "test/workflow"
    run_id: str
    forge: str
    repo: str
    layer: str = ""
    agent_id: str = ""
    kind: SpendKind = "model_call"
    at: datetime
    usd: float


class InMemorySpendRecord:
    """Costs as (forge, repo, layer, agent_id, when, usd), and as
    recorded facts that also name their run and kind.

    Both count towards what a scope spent. Only the recorded facts are
    listed by run, since a bare cost names none.
    """

    def __init__(self) -> None:
        self.costs: list[tuple[str, str, str, str, datetime, float]] = []
        self.recorded: list[RecordedCost] = []
        #: What each run has spent, as (run_id, usd).
        self.run_costs: list[tuple[str, float]] = []

    def _all(self) -> list[tuple[str, str, str, str, datetime, float]]:
        return self.costs + [
            (one.forge, one.repo, one.layer, one.agent_id, one.at, one.usd)
            for one in self.recorded
        ]

    def spent_by_run(
        self,
        since: datetime,
        until: datetime,
        forge: str = "",
        repo: str = "",
        layer: str = "",
        agent_id: str = "",
        owner: str = "",
    ) -> tuple[RunCost, ...]:
        found: defaultdict[
            tuple[str, str, str, str, str, str, SpendKind],
            list[RecordedCost],
        ] = defaultdict(list)
        for one in self.recorded:
            if (
                since <= one.at < until
                and forge in ("", one.forge)
                and owner in ("", owner_of(one.repo))
                and repo in ("", one.repo)
                and layer in ("", one.layer)
                and agent_id in ("", one.agent_id)
            ):
                key = (
                    one.workflow_id,
                    one.run_id,
                    one.forge,
                    one.repo,
                    one.layer,
                    one.agent_id,
                    one.kind,
                )
                found[key].append(one)
        rows = [
            RunCost(
                workflow_id=workflow_id,
                run_id=run_id,
                forge=one_forge,
                repo=one_repo,
                layer=one_layer,
                agent_id=one_agent,
                kind=kind,
                since=since,
                until=until,
                first=min(one.at for one in facts),
                last=max(one.at for one in facts),
                usd=sum(one.usd for one in facts),
                facts=len(facts),
            )
            for (
                workflow_id,
                run_id,
                one_forge,
                one_repo,
                one_layer,
                one_agent,
                kind,
            ), facts in found.items()
        ]
        rows.sort(
            key=lambda row: (
                row.workflow_id,
                row.run_id,
                row.layer,
                row.agent_id,
                row.kind,
            )
        )
        rows.sort(key=lambda row: row.last, reverse=True)
        return tuple(rows)

    def spent(
        self,
        since: datetime,
        until: datetime,
        forge: str = "",
        repo: str = "",
        layer: str = "",
        agent_id: str = "",
        owner: str = "",
    ) -> Spent:
        found = [
            usd
            for one_forge, one_repo, one_layer, one_agent, when, usd in (
                self._all()
            )
            if since <= when < until
            and forge in ("", one_forge)
            and owner in ("", owner_of(one_repo))
            and repo in ("", one_repo)
            and layer in ("", one_layer)
            and agent_id in ("", one_agent)
        ]
        return Spent(
            forge=forge,
            owner=owner,
            repo=repo,
            layer=layer,
            agent_id=agent_id,
            since=since,
            until=until,
            usd=sum(found),
            facts=len(found),
        )

    def spent_by_scope(
        self,
        since: datetime,
        until: datetime,
        forge: str = "",
        repo: str = "",
        layer: str = "",
        agent_id: str = "",
        owner: str = "",
    ) -> tuple[Spent, ...]:
        found: defaultdict[tuple[str, str, str, str], list[float]] = (
            defaultdict(list)
        )
        for (
            one_forge,
            one_repo,
            one_layer,
            one_agent,
            when,
            usd,
        ) in self._all():
            if not (
                since <= when < until
                and forge in ("", one_forge)
                and owner in ("", owner_of(one_repo))
                and repo in ("", one_repo)
                and layer in ("", one_layer)
                and agent_id in ("", one_agent)
            ):
                continue
            found[(one_forge, one_repo, one_layer, one_agent)].append(usd)
        return tuple(
            Spent(
                forge=one_forge,
                owner=owner or owner_of(one_repo),
                repo=one_repo,
                layer=one_layer,
                agent_id=one_agent,
                since=since,
                until=until,
                usd=sum(costs),
                facts=len(costs),
            )
            for (one_forge, one_repo, one_layer, one_agent), costs in sorted(
                found.items()
            )
        )

    def spent_in_run(self, run_id: str) -> RunSpend:
        found = [usd for one, usd in self.run_costs if one == run_id]
        return RunSpend(run_id=run_id, usd=sum(found), facts=len(found))
