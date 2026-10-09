# ADR 003: Running a use case under Temporal

## Status

Proposed, 2026-10-09.

## Decision

The workflow engine is Temporal. ADR 002 says a workflow is
application code, a shell around one use case. This record says how
the worker application runs a use case under Temporal, and what that
asks of whoever edits one.

### What Temporal does

A workflow is a function Temporal can stop and continue, on another
machine or after a restart. It does so by recording a history: each
step the workflow asked for, and what came back. To continue a run,
Temporal runs the workflow's code again from the top and answers each
step from the history, until the code reaches the first step with no
answer.

Two things follow, and the rest of this record is their consequence:

- A workflow's code must ask for the same steps in the same order
  every time it is run over the same history.
- Anything that reaches outside, a database, a store, a model, the
  clock, happens in an activity. An activity is an ordinary function
  that Temporal calls once, records the result of, and retries if it
  fails.

### Two ways to run a use case

The worker application chooses one for each use case. The use case is
the same class either way and imports nothing from Temporal.

| A use case that | Runs |
|---|---|
| makes a few slow or paid calls, each with a small answer | in the workflow |
| waits on a person or on another system | in the workflow |
| loads a lot and computes | as one activity |
| makes many cheap calls | as one activity |

In the workflow. The application constructs the use case with
proxies in place of adapters. A proxy has an interface's methods, and
each one asks Temporal to run an activity; the activity calls the
real adapter. Each call the use case makes is then a recorded step:
a run that stops after the third call continues at the fourth, and a
call that fails is retried alone.

As one activity. The application constructs the use case with its
real adapters inside an activity and calls `execute`. The whole use
case is one recorded step, and a failure runs all of it again.

### What a use case needs to run in the workflow

- It is `async`, and awaits each call to an interface.
- It reads the time, and learns which run it is in, through
  interfaces. It does not call the clock, and it makes no random
  choice.
- It makes its calls in an order that is the same in every process.
  Iterating a set is not: its order changes from one process to the
  next.
- What an interface answers with is small: a verdict, or a reference
  to something stored. Every answer is written to the history, and a
  history has a size limit.

A use case that runs as one activity needs none of these, and may be
written without `async`.

### Editing a use case that runs in the workflow

Such a use case is workflow code. Adding, removing or reordering a
call to an interface changes the steps it asks for, and every run in
flight then fails when it continues: its history has the old steps
and the code asks for the new ones.

The change is guarded so that a run in flight keeps the steps it
started with and a new run takes the new ones:

- A workflow guards with Temporal's own `workflow.patched`.
- A use case cannot import Temporal, so it asks an interface whether
  this run takes the change. The worker's adapter answers with
  `workflow.patched`; a test's answers as the test says.

When no run that started before the change is left, the old branch
is deleted and the guard is marked as retired.

### Tests

Each workflow has a history recorded from a real run, kept with its
tests, and a test that replays the current code over it. A change to
the steps fails that test before it reaches a deployment.
Recording the history again makes the test pass and leaves the runs
in flight broken, so a history is recorded again only with the guard
that makes the change safe.

## Rules

1. A use case imports nothing from Temporal, whichever way it runs.
2. Only the worker application decides how a use case runs, and it
   holds the workflows, the activities and the proxies.
3. Everything that reaches outside happens in an activity.
4. An interface a workflow calls answers with a verdict or a
   reference, never with the bulk it refers to.
5. A change to the calls of a use case that runs in the workflow, or
   to the steps of a workflow, is guarded.
6. Each workflow has a recorded history that a test replays.
7. A workflow and an activity are registered under a name with no
   module path in it, so code can move without breaking a run.

## Consequences

A use case can move between the two ways without being rewritten: a
use case that grows a wait on a person moves into the workflow by
becoming `async`.

An edit that looks like a refactor, reordering two calls, can break
every run in flight. The replayed history is what catches it.

Moving a call into the workflow costs time and history: Temporal
records several events for each activity, where one activity for the
whole use case records them once.
