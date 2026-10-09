"""The journal entry, and how its id is made.

The journal is a table of facts: things that happened, such as "this
archive event was stored". A fact is written once and never changed or
deleted.

Each context decides which facts it records and what to call them. The
archive's are in ``bugflow.archive.domain.facts``. This module holds no
list of them.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from bugflow.shared.domain.values.correlation import Correlation

# Never change this. Every id is made from it, so a new value would
# give every existing fact a different id.
_NAMESPACE = uuid5(NAMESPACE_DNS, "journal.bugflow")


@dataclass(frozen=True, kw_only=True)
class JournalEntry:
    """One fact in the journal.

    ``forge``, ``repo``, ``pr_number`` and ``commit_sha`` say what the fact
    is about. ``workflow_id`` and ``run_id`` say which run recorded it.
    ``payload`` holds the details, and must be something JSON can
    represent.
    """

    event_id: UUID
    occurred_at: datetime
    #: The kind of fact, named by the context that records it in the
    #: form ``context.what_happened``, such as ``archive.sealed``.
    event_type: str
    forge: str
    repo: str
    pr_number: int | None
    commit_sha: str | None
    #: For a fact about a review: the version of the review rules that
    #: applied. None otherwise.
    corpus_version: str | None
    workflow_id: str
    run_id: str
    payload: dict[str, Any]
    #: For a fact about one review agent: that agent's id. None
    #: otherwise.
    agent_id: str | None = None
    #: Which build of the software recorded the fact. The journal's
    #: adapter fills this in; code that creates an entry leaves it None.
    build: str | None = None


def fact_id(*parts: str) -> UUID:
    """Make a fact's id from the things that identify it.

    The same parts always give the same id. The journal ignores an entry
    whose id it already has, so recording a fact twice, after a retry or a
    repeated request, leaves one entry.

    The caller chooses the parts. For "this archive event was stored" they
    are the ledger and the event's name, so storing the same event again is
    the same fact.
    """
    return uuid5(_NAMESPACE, "/".join(parts))


def event_id(correlation: Correlation, event_type: str, key: str) -> UUID:
    """Make the id of a fact that belongs to one step of one workflow run,
    from the run, the fact's type and a key that tells the step apart from
    the run's other steps. If the step is retried, it records the same fact
    under the same id.
    """
    return fact_id(
        correlation.workflow_id, correlation.run_id, event_type, key
    )
