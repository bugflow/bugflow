"""A finding raised by a stocktake's review, and what a person decided
about it."""

from dataclasses import dataclass
from datetime import datetime

from bugflow.shared.domain.values.disposition import Disposition


@dataclass(frozen=True, kw_only=True)
class StocktakeFinding:
    """One finding of one stocktake's review, as read back from the
    journal."""

    #: The id of the journal entry that recorded the finding. It
    #: identifies the finding: a disposition refers to it by this id.
    event_id: str
    forge: str
    repo: str
    #: The layer whose stocktake raised it.
    layer: str
    agent_id: str
    head_sha: str | None
    #: The workflow run of the stocktake that raised it.
    workflow_id: str
    run_id: str
    found_at: datetime
    #: Its position among the findings the reviewer gave, counting from
    #: zero.
    index: int
    #: The file or place the finding is about.
    where: str
    #: The words the finding quotes.
    quote: str
    #: What the reviewer says is wrong.
    claim: str
    kind: str = ""


@dataclass(frozen=True, kw_only=True)
class FindingDisposition:
    """What a person recorded was done about one finding."""

    #: The ``event_id`` of the finding.
    finding: str
    disposition: Disposition
    #: The question the finding was routed to, if it was. Empty
    #: otherwise.
    question_id: str
    disposed_at: datetime
