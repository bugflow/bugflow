"""What this deployment spent, kept in memory, for tests."""

from datetime import datetime

from bugflow.review.domain.models.spend import RunSpend, Spent


class InMemorySpendRecord:
    """Costs as (forge, repo, layer, agent_id, when, usd)."""

    def __init__(self) -> None:
        self.costs: list[tuple[str, str, str, str, datetime, float]] = []
        #: What each run has spent, as (run_id, usd).
        self.run_costs: list[tuple[str, float]] = []

    def spent(
        self,
        since: datetime,
        until: datetime,
        forge: str = "",
        repo: str = "",
        layer: str = "",
        agent_id: str = "",
    ) -> Spent:
        found = [
            usd
            for one_forge, one_repo, one_layer, one_agent, when, usd in (
                self.costs
            )
            if since <= when < until
            and forge in ("", one_forge)
            and repo in ("", one_repo)
            and layer in ("", one_layer)
            and agent_id in ("", one_agent)
        ]
        return Spent(
            forge=forge,
            repo=repo,
            layer=layer,
            agent_id=agent_id,
            since=since,
            until=until,
            usd=sum(found),
            facts=len(found),
        )

    def spent_in_run(self, run_id: str) -> RunSpend:
        found = [usd for one, usd in self.run_costs if one == run_id]
        return RunSpend(run_id=run_id, usd=sum(found), facts=len(found))
