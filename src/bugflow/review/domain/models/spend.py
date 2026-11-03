"""What has actually been spent, as the journal recorded it.

A ceiling says what a run may spend; this says what runs did spend. The
two are read together at a dispatch, and separately on a page, and both
must be the same number or the page and the dispatcher disagree about
whether a deployment is over its limit.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, get_args

#: The kind of fact a cost was recorded on. Each kind is kept in a
#: table of its own (ADR 007): a call to a model, a delegated agent's
#: session, a checked policy, and a stocktake's review.
SpendKind = Literal[
    "model_call", "agent_dispatch", "policy_check", "stocktake_review"
]

#: Every kind of fact that carries a cost, in the order a page lists
#: them.
SPEND_KINDS: tuple[SpendKind, ...] = get_args(SpendKind)


@dataclass(frozen=True, kw_only=True)
class Spent:
    """What one scope spent over a window.

    The scope is as far as the facts go: an agent run names its layer and
    its reviewer, a judge's call names neither, so a figure for a whole
    repository holds both and a figure for a layer holds only what the
    layer's own runs cost.
    """

    forge: str
    repo: str
    layer: str
    agent_id: str
    since: datetime
    until: datetime
    #: The owner whose repositories it covers, or empty.
    owner: str = ""
    #: What it cost, in dollars, summed from what each fact recorded.
    usd: float
    #: How many runs and calls the figure is made of. A sum with no
    #: count cannot be told from a sum of nothing.
    facts: int


@dataclass(frozen=True, kw_only=True)
class RunSpend:
    """What one run has spent so far, over every fact it recorded.

    Every cost, not only the model's: a per-event ceiling is what one
    run may spend, and a run that dispatched an agent and then judged
    spent both. Read while the run is still going, so it is what has
    been recorded rather than what the run will finally cost.
    """

    run_id: str
    usd: float
    facts: int


@dataclass(frozen=True, kw_only=True)
class RunCost:
    """What one run spent in a window, on one kind of fact, under one
    layer and one agent.

    The rows a total is made of. A figure for a scope is the sum of the
    rows that match it, so every total on a page can be followed down to
    the runs that produced it, and from a run to its facts.

    A run is split by layer, agent and kind because its facts are: a
    run that dispatched a reviewer and then judged has a row for the
    reviewer's session and a row for the judge's calls, which name no
    agent.
    """

    #: The workflow and the run, which together find the run's facts.
    workflow_id: str
    run_id: str
    forge: str
    repo: str
    #: The pace layer the facts name, or empty where they name none.
    layer: str
    #: The agent the facts name, or empty where they name none.
    agent_id: str
    kind: SpendKind
    #: The window the row was read over, as for :class:`Spent`.
    since: datetime
    until: datetime
    #: When the earliest and the latest of its facts were recorded.
    first: datetime
    last: datetime
    usd: float
    facts: int
