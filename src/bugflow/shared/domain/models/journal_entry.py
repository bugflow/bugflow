"""A fact in the journal, and the id it is known by.

The journal is append-only: a fact is recorded once and never changed.
Every context records its own facts and names their types itself, as
``archive.sealed`` is the archive's; nothing here lists them.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_DNS, UUID, uuid5

from bugflow.shared.domain.values.correlation import Correlation

# Fixed. Changing it changes every id the journal will ever derive.
_NAMESPACE = uuid5(NAMESPACE_DNS, "journal.bugflow")


@dataclass(frozen=True, kw_only=True)
class JournalEntry:
    event_id: UUID
    occurred_at: datetime
    #: What kind of fact this is, as the context that records it names
    #: it: ``{context}.{what happened}``.
    event_type: str
    forge: str
    repo: str
    pr_number: int | None
    commit_sha: str | None
    #: The version of the reviewers' corpus in effect, for a fact of a
    #: review.
    corpus_version: str | None
    workflow_id: str
    run_id: str
    payload: dict[str, Any]
    #: The review agent the fact belongs to, for a fact that belongs to
    #: one.
    agent_id: str | None = None
    #: The build that recorded the fact. Stamped by the journal's adapter
    #: and not by whoever made the entry: it is a property of the
    #: process, and a producer that had to pass it could forget.
    build: str | None = None


def fact_id(*parts: str) -> UUID:
    """Derive a fact's id from what makes it that fact and no other.

    The same parts give the same id, so a fact recorded twice, by a
    retry or a repeated request, is one fact. A context chooses the
    parts: an archive event sealed is its ledger and its name, and is
    one fact however often it is sent.
    """
    return uuid5(_NAMESPACE, "/".join(parts))


def event_id(correlation: Correlation, event_type: str, key: str) -> UUID:
    """Derive a fact's id from the run, its type and a key local to the
    step, for a fact that belongs to one step of one run: the step
    retried after a partial write records the same fact under the same
    id."""
    return fact_id(
        correlation.workflow_id, correlation.run_id, event_type, key
    )
