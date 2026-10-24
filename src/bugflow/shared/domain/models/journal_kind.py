"""Which journal a fact belongs to, by what the fact is (ADR 006).

Every event type belongs to one of five kinds, and a fact is written to
the journal of its kind. The map is here, in the shared kernel, because
a fact's kind is a property of the fact and not of the context or the
program that writes it: the forge's use cases run in the worker as well
as in the ingress, and a division by writer would put one fact's rows
in two tables.

A new event type is added here before an adapter writes it, and a test
holds every type the contexts name to this map.
"""

#: The journals, in the order the records normalise them.
KINDS = ("archive", "forge", "review", "stocktake", "policy")

#: The kind of each event type.
KIND_OF: dict[str, str] = {
    # What the keeper did with a ledger.
    "archive.sealed": "archive",
    "archive.bound": "archive",
    "archive.refused": "archive",
    # What happened to a pull request on its forge.
    "delivery.received": "forge",
    "webhook.reconciled": "forge",
    "pr.observed": "forge",
    "pr.closed": "forge",
    "pr.merged": "forge",
    "reaction.recorded": "forge",
    "finding.dismissed": "forge",
    # What an evaluation did.
    "agent.dispatched": "review",
    "completion.received": "review",
    "review.graded": "review",
    "judge.invoked": "review",
    "llm.called": "review",
    "policy.checked": "review",
    "finding.raised": "review",
    "finding.resolved": "review",
    "finding.rewritten": "review",
    "finding.withheld": "review",
    "action.taken": "review",
    # What a periodic review of a repository did.
    "stocktake.taken": "stocktake",
    "stocktake.dispatched": "stocktake",
    "stocktake.reviewed": "stocktake",
    "stocktake.found": "stocktake",
    "stocktake.graded": "stocktake",
    # What was done to the policies a server judges by.
    "policies.deployed": "policy",
    "policy.calibrated": "policy",
}


class UnplacedFactError(ValueError):
    """An event type no journal is named for."""


def kind_of(event_type: str) -> str:
    """The kind of this event type, or UnplacedFactError."""
    try:
        return KIND_OF[event_type]
    except KeyError:
        raise UnplacedFactError(
            f"no journal is named for {event_type!r}; add it to KIND_OF"
        ) from None


def journal_of(event_type: str) -> str:
    """The table a fact of this type is written to."""
    return f"{kind_of(event_type)}_journal"
