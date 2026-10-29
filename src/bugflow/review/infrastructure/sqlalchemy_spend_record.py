"""What this deployment has spent, read from the journal.

Four kinds of fact carry a cost, each in its own table (ADR 007). A
call to a model records the proxy's own figure as an integer of
nanodollars in ``model_call``. A delegated run records its session's
cost in dollars in ``agent_dispatch`` when it is collected, a checked
policy its cost in ``policy_check``, and a stocktake's review its cost
in ``stocktake_review``. All are summed here, in dollars, because a
ceiling is in dollars and one number is what a caller asked for. A fact
whose row records no cost is not counted.

The journal is read through a relation named at construction, so a
deployment that keeps a view over the journal, such as one that leaves
out rows no watched repository recorded, reads spend through that view.
Each cost table is joined to that relation by the event's id.
"""

from datetime import datetime

import sqlalchemy as sa

from bugflow.review.domain.models.spend import RunSpend, Spent
from bugflow.shared.infrastructure.database import engine_url

#: A nanodollar is a billionth, which is what the proxy's figures are
#: kept as so that a million of them summed is still exact.
_NANODOLLARS = 1_000_000_000.0


def _costs(relation: str) -> str:
    """Every costed fact as one row: when and where it was recorded, the
    agent it names, the layer it belongs to, and its cost in dollars."""
    return f"""
select j.occurred_at, j.forge, j.repo, j.run_id, j.agent_id,
       null::text as layer, m.cost_nanodollars / :nano as usd
  from {relation} j join model_call m on m.event_id = j.event_id
 where m.cost_nanodollars is not null
union all
select j.occurred_at, j.forge, j.repo, j.run_id,
       coalesce(j.agent_id, d.agent_id), null::text, d.cost_usd
  from {relation} j join agent_dispatch d on d.event_id = j.event_id
 where d.cost_usd is not null
union all
select j.occurred_at, j.forge, j.repo, j.run_id, j.agent_id,
       null::text, p.cost_usd
  from {relation} j join policy_check p on p.event_id = j.event_id
 where p.cost_usd is not null
union all
select j.occurred_at, j.forge, j.repo, j.run_id,
       coalesce(j.agent_id, s.agent_id), s.layer, s.cost_usd
  from {relation} j join stocktake_review s on s.event_id = j.event_id
 where s.cost_usd is not null
"""


def _window_query(relation: str) -> str:
    return f"""
select coalesce(sum(usd), 0) as usd, count(*) as facts
from ({_costs(relation)}) costs
where occurred_at >= :since and occurred_at < :until
  and (:forge = '' or forge = :forge)
  and (:owner = '' or split_part(repo, '/', 1) = :owner)
  and (:repo = '' or repo = :repo)
  and (:layer = '' or layer = :layer)
  and (:agent = '' or agent_id = :agent)
"""


def _run_query(relation: str) -> str:
    # No time bound: a run is bounded by itself.
    return f"""
select coalesce(sum(usd), 0) as usd, count(*) as facts
from ({_costs(relation)}) costs
where run_id = :run
"""


class SqlAlchemySpendRecord:
    def __init__(self, database_url: str, relation: str = "journal") -> None:
        """``relation`` is the table or view the journal is read
        through. It has the journal's columns."""
        self._engine = sa.create_engine(engine_url(database_url))
        self._window = sa.text(_window_query(relation))
        self._run = sa.text(_run_query(relation))

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
        with self._engine.connect() as connection:
            row = connection.execute(
                self._window,
                {
                    "nano": _NANODOLLARS,
                    "since": since,
                    "until": until,
                    "forge": forge,
                    "owner": owner,
                    "repo": repo,
                    "layer": layer,
                    "agent": agent_id,
                },
            ).one()
        return Spent(
            forge=forge,
            owner=owner,
            repo=repo,
            layer=layer,
            agent_id=agent_id,
            since=since,
            until=until,
            usd=float(row.usd),
            facts=int(row.facts),
        )

    def spent_in_run(self, run_id: str) -> RunSpend:
        with self._engine.connect() as connection:
            row = connection.execute(
                self._run, {"nano": _NANODOLLARS, "run": run_id}
            ).one()
        return RunSpend(
            run_id=run_id, usd=float(row.usd), facts=int(row.facts)
        )
