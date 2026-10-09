"""The facts this context writes to the journal, and how the id of a
delivery's fact is made."""

from uuid import UUID

from bugflow.shared.domain.models.journal_entry import fact_id

#: A delivery arrived from a forge and was accepted.
DELIVERY_RECEIVED = "delivery.received"

#: A snapshot of a pull request was taken and stored.
PR_OBSERVED = "pr.observed"

#: A pull request was merged.
PR_MERGED = "pr.merged"

#: A person dismissed a policy's findings with a ``/dismiss`` comment.
FINDING_DISMISSED = "finding.dismissed"

#: A repository's webhooks were compared with what is wanted, and
#: changed where they differed.
WEBHOOK_RECONCILED = "webhook.reconciled"


def delivery_id(forge: str, delivery_id: str) -> UUID:
    """The id of a "delivery received" fact, made from the forge and the
    forge's own id for the delivery.

    It does not depend on which workflow run handles the delivery. So if
    the forge sends a delivery a second time, it maps to the fact already
    recorded and is not recorded again.
    """
    return fact_id("delivery", forge, delivery_id)
