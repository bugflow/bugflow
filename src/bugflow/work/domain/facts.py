"""The facts this context writes to the journal, and the facts of other
contexts that it reads."""

#: A task was handed to a runner, or something later was learned about
#: that run. The entry's payload has a ``step`` that says which.
AGENT_DISPATCHED = "agent.dispatched"

#: A runner reported that a run finished. One is recorded for every
#: completion, whether or not anything was waiting for it.
COMPLETION_RECEIVED = "completion.received"

#: A snapshot of a pull request was taken and stored. The forge context
#: records this fact. This context only reads it, to tell which pull
#: requests a backfill has already been through.
PR_OBSERVED = "pr.observed"

#: A judge was asked to assess a pull request against one policy. The
#: review context records this fact. This context only reads it, to tell
#: which pull requests a backfill has already had judged.
JUDGE_INVOKED = "judge.invoked"
