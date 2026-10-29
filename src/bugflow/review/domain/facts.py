"""The facts this context writes to the journal."""

from datetime import datetime
from uuid import UUID

from bugflow.shared.domain.models.journal_entry import fact_id

#: A finding was raised.
FINDING_RAISED = "finding.raised"

#: A finding raised by an earlier evaluation was not raised by this one,
#: and the policy it belongs to did answer this time.
FINDING_RESOLVED = "finding.resolved"

#: A judge was asked about one policy. The payload says how it went.
JUDGE_INVOKED = "judge.invoked"

#: A checked policy was run.
POLICY_CHECKED = "policy.checked"

#: One call was made to a language model.
LLM_CALLED = "llm.called"

#: A checkout agent's task was handed to a runner, or something later
#: was learned about that run. The payload's ``step`` says which.
AGENT_DISPATCHED = "agent.dispatched"

#: A grader read a checkout agent's write-up and gave a verdict.
REVIEW_GRADED = "review.graded"

#: Something was written to the pull request: a comment, a label or a
#: commit status. The payload's ``action`` says which.
ACTION_TAKEN = "action.taken"

#: The words a finding quoted are no longer in the pull request.
FINDING_REWRITTEN = "finding.rewritten"

#: A warning was kept out of the pull request on purpose.
FINDING_WITHHELD = "finding.withheld"

#: A snapshot of a pull request was taken and stored. The forge context
#: records this fact. This context only reads it, to learn which commit
#: an evaluation read.
PR_OBSERVED = "pr.observed"

#: A person dismissed a policy's findings on a pull request. The forge
#: context records this fact. This context only reads it.
FINDING_DISMISSED = "finding.dismissed"

#: A person reacted to a comment this server posted. Recorded when the
#: pull request closes.
REACTION_RECORDED = "reaction.recorded"

#: A pull request closed. The payload says whether it merged and which
#: findings were still standing.
PR_CLOSED = "pr.closed"

#: A stocktake ran for a layer. The payload gives the range it covered.
#: The latest of these for a layer is the layer's mark.
STOCKTAKE_TAKEN = "stocktake.taken"

#: A pull request was merged. The forge context records this fact. This
#: context only reads it, to learn what a stocktake's range holds.
PR_MERGED = "pr.merged"

#: A stocktake's review was handed to a runner, or could not be. The
#: payload's ``step`` says which.
STOCKTAKE_DISPATCHED = "stocktake.dispatched"

#: A stocktake's review finished. The payload has its outcome, its cost
#: and its write-up.
STOCKTAKE_REVIEWED = "stocktake.reviewed"

#: One finding of a stocktake's review.
STOCKTAKE_FOUND = "stocktake.found"

#: A grader read a stocktake's write-up and gave a verdict.
STOCKTAKE_GRADED = "stocktake.graded"

#: An operator set what a gnome does on a repository (ADR 008). The
#: payload has the behaviour, the profile, who set them, and what they
#: replaced.
GNOME_SET = "gnome.set"


def gnome_set_id(
    forge: str,
    repo: str,
    gnome: str,
    setting: tuple[str, str],
    was: tuple[str, str] | None,
    when: datetime,
) -> UUID:
    """The id of a "gnome set" fact, made from the repository, the gnome,
    the behaviour and profile it was set to and from, and the time.
    Setting it again later is a new fact, and so is a second change in
    the same instant."""
    return fact_id(
        "gnome-set",
        forge,
        repo,
        gnome,
        *setting,
        *(was or ("", "")),
        when.isoformat(),
    )


#: An operator declared where one repository's period on a layer
#: begins, or withdrew it. The payload has the layer, the boundary, null
#: when withdrawn, what it replaced, and who declared it.
BOUNDARY_DECLARED = "boundary.declared"

#: An operator declared where this server's periods of one cadence
#: begin, or withdrew it. It names no repository. The payload is as a
#: boundary's, with the cadence in place of the layer.
CADENCE_DECLARED = "cadence.declared"

#: An operator declared the share of a repository's warnings withheld.
#: The payload has the share, what it replaced, and who declared it.
WITHHOLDING_DECLARED = "withholding.declared"

#: An operator allowed a scope to spend per one cadence, or revoked
#: that allowance. It names the repository the scope names, or none.
#: The payload has the rest of the scope, the cadence, the money and the
#: turns, whether the allowance is held after it and was held before,
#: what it replaced, and who declared it.
ALLOWANCE_DECLARED = "allowance.declared"


def declaration_id(event_type: str, *parts: str, when: datetime) -> UUID:
    """The id of a declaration's fact, made from what it declares, what
    it replaced and the time. Declaring the same again later is a new
    fact, and so is a second change in the same instant."""
    return fact_id(event_type, *parts, when.isoformat())
