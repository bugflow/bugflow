"""Decide which warnings are kept out of a pull request on purpose.

A repository can be set up so that a share of its warnings is not shown
to the author. Comparing what happens to those with what happens to the
warnings that were shown tells whether authors act on warnings.

Which warnings are kept out is decided by a hash, not a random number.
The hash is of the pull request and the finding's policy, clause and
subject. So the same warning is kept out every time that pull request is
evaluated, and a workflow that is replayed decides as it did the first
time.

Only a warning can be kept out. A finding of severity "fail" always
reaches the author, because it fails the commit status.
"""

import hashlib

from bugflow.review.domain.models.finding import Finding
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

_ONE = float(1 << 64)


def drawn(ref: PullRequestRef, finding: Finding, share: float) -> bool:
    """Whether this finding is one of the warnings kept out of this
    pull request.

    ``share`` is the share to keep out, from 0 to 1. Always False for a
    finding that is not a warning, and for a share of 0.
    """
    if finding.severity != "warn" or share <= 0.0:
        return False
    key = "/".join(
        [
            ref.forge,
            ref.owner,
            ref.repo,
            str(ref.number),
            finding.policy_id,
            finding.clause,
            finding.subject,
        ]
    )
    digest = hashlib.sha256(key.encode()).digest()
    return int.from_bytes(digest[:8], "big") / _ONE < share
