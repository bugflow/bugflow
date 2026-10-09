"""The facts the archive records in the journal, and the id of each.

An id is derived from what makes the fact that fact, so one recorded
twice is recorded once.
"""

from datetime import datetime
from uuid import UUID

from bugflow.shared.domain.models.journal_entry import fact_id

#: An operator bound a ledger to a scope of a repository, so that its
#: archive is kept here: where it was bound before, if it was, and the
#: other ledgers the scope already had.
BOUND = "archive.bound"

#: An event of a bound ledger was kept, once the keeper had verified
#: it: the event's name, the head and root after it, who appended it
#: and what the client claimed of where it came from.
SEALED = "archive.sealed"

#: An event a client sent to a bound ledger was turned away, with the
#: kind of refusal: nothing of it was kept.
REFUSED = "archive.refused"


def bound_id(
    ledger_id: str, forge: str, repo: str, scope: str, when: datetime
) -> UUID:
    """From what the binding says and when: a ledger bound to one place,
    away, and back is three facts."""
    return fact_id(
        "archive-bound", ledger_id, forge, repo, scope, when.isoformat()
    )


def sealed_id(ledger_id: str, name: str) -> UUID:
    """From the event it is of: a ledger has one event of a name, so the
    event sent twice is one fact."""
    return fact_id("archive-sealed", ledger_id, name)


def refused_id(ledger_id: str, name: str, kind: str, when: datetime) -> UUID:
    """From what the refusal says and when: the same event refused twice
    was refused twice."""
    return fact_id("archive-refused", ledger_id, name, kind, when.isoformat())
