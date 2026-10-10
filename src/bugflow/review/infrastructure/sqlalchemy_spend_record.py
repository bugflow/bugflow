"""What this deployment has spent, read from the journal.

Two kinds of fact carry a cost and they carry it differently. A
delegated run records its session's cost as dollars under ``cost.usd``
when it is collected; a call to a model records the proxy's own figure
as an integer of nanodollars. Both are summed here, in dollars, because
a ceiling is in dollars and one number is what a caller asked for.

The journal is read through a relation named at construction, so a
deployment that keeps a view over the journal, such as one that leaves
out rows no watched repository recorded, reads spend through that view.
"""

from datetime import datetime

import sqlalchemy as sa

from bugflow.review.domain.models.spend import RunSpend, Spent
from bugflow.shared.infrastructure.database import engine_url

#: A nanodollar is a billionth, which is what the proxy's figures are
#: kept as so that a million of them summed is still exact.
_NANODOLLARS = 1_000_000_000.0

#: The cost each kind of fact recorded, in dollars.
_COST = """
coalesce(sum(
  case
    when event_type = 'llm.called'
      then (payload->>'cost_nanodollars')::numeric / :nano
    else (payload->'cost'->>'usd')::numeric
  end
), 0) as usd,
count(*) as facts
"""

#: Which facts carry a cost at all.
_COSTED = """
(
  (event_type = 'llm.called' and payload ? 'cost_nanodollars')
  or (event_type <> 'llm.called' and payload->'cost' ? 'usd')
)
"""


def _window_query(relation: str) -> str:
    return f"""
select {_COST}
from {relation}
where occurred_at >= :since and occurred_at < :until
  and {_COSTED}
  and (:forge = '' or forge = :forge)
  and (:repo = '' or repo = :repo)
  and (:layer = '' or payload->>'layer' = :layer)
  and (:agent = '' or coalesce(agent_id, payload->>'agent_id') = :agent)
"""


def _run_query(relation: str) -> str:
    # No time bound: a run is bounded by itself.
    return f"""
select {_COST}
from {relation}
where run_id = :run
  and {_COSTED}
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
    ) -> Spent:
        with self._engine.connect() as connection:
            row = connection.execute(
                self._window,
                {
                    "nano": _NANODOLLARS,
                    "since": since,
                    "until": until,
                    "forge": forge,
                    "repo": repo,
                    "layer": layer,
                    "agent": agent_id,
                },
            ).one()
        return Spent(
            forge=forge,
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
