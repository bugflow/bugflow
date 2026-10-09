"""The three facts the archive writes to the journal, and how the id of each
is made.

An id is made from the details that identify the fact, so that writing the
same fact twice leaves one journal entry.
"""

from datetime import datetime
from uuid import UUID

from bugflow.shared.domain.models.journal_entry import fact_id

#: An operator registered a ledger with this server. The payload says
#: which repository and scope it was registered for, what it was
#: registered for before, and which other ledgers that scope has.
BOUND = "archive.bound"

#: An event was checked and stored. The payload has the event's name,
#: the ledger's state afterwards, who sent it, and what the client
#: said about where it came from.
SEALED = "archive.sealed"

#: An event was refused and nothing was stored. The payload has the
#: kind of refusal.
REFUSED = "archive.refused"


def bound_id(
    ledger_id: str, forge: str, repo: str, scope: str, when: datetime
) -> UUID:
    """The id of a "ledger registered" fact, made from the ledger, where it
    was registered, and the time. Registering a ledger again later is a new
    fact.
    """
    return fact_id(
        "archive-bound", ledger_id, forge, repo, scope, when.isoformat()
    )


def sealed_id(ledger_id: str, name: str) -> UUID:
    """The id of an "event stored" fact, made from the ledger and the event's
    name. A ledger has one event of each name, so sending the same event
    twice gives one fact.
    """
    return fact_id("archive-sealed", ledger_id, name)


def refused_id(ledger_id: str, name: str, kind: str, when: datetime) -> UUID:
    """The id of an "event refused" fact, made from the ledger, the event's
    name, the kind of refusal, and the time. The same event refused on two
    occasions is two facts.
    """
    return fact_id("archive-refused", ledger_id, name, kind, when.isoformat())
