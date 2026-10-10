"""What has actually been spent, as the journal recorded it.

A ceiling says what a run may spend; this says what runs did spend. The
two are read together at a dispatch, and separately on a page, and both
must be the same number or the page and the dispatcher disagree about
whether a deployment is over its limit.
"""

from dataclasses import dataclass
from datetime import datetime


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
