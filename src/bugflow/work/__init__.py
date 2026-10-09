"""The work context: handing a task to something that will do it, and
reading back what it did.

Words used throughout:

- Runner: whatever does the work. It may be a language model running in
  a hosted container, or a person working with their own coding agent.
- Task: what a runner is asked to do: instructions, what it may read,
  what it may spend, and the shape its answer must have.
- Run: one attempt at a task, and what came of it.
- Dispatch: to start a run.
- Handle: a small record that identifies a dispatched run, so that a
  later step can come back to it.
- Collect: to read what a run produced.
- Artifact: a run's answer, as data in the shape the task asked for.
- Write-up: the prose a run wrote alongside its answer.
- Completion: a runner's message that one of its runs has finished.
- Worktree: a directory holding one commit of a repository, prepared
  for a runner to read.
- Backfill: reviewing a repository's old, closed pull requests.

This context does not know what the work is for. Reviewing a pull
request is one use of it.
"""
