"""The facts this context writes to the journal."""

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
