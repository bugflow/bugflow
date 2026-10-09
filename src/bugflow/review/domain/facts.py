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
