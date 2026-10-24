# ADR 006: One journal for each kind of fact

## Status

Proposed, 2026-10-24.

## Decision

The journal is divided into five tables by what a fact is: what the
keeper did with a ledger, what happened to a pull request on its
forge, what an evaluation did, what a periodic review of a repository
did, and what was done to the policies a server judges by. Each is a
table of the journal's shape under the journal's rule, each event type
belongs to one of them, and `journal` stays as a view over the five so
that every reader reads on unchanged until it moves.

Each journal is then normalised on its own: its payload unpacked into
tables that say what one row is, by the records that follow this one.
That is why the division comes first, and why it is by kind and not by
the program that writes a fact: the forge's use cases run in the
worker as well as the ingress, so a division by writer would put one
fact's rows in two tables.

### The journals

| Table | One row is | Event types |
|---|---|---|
| `archive_journal` | what the keeper did with a ledger | `archive.sealed`, `archive.bound`, `archive.refused` |
| `forge_journal` | what happened to a pull request on its forge | `delivery.received`, `webhook.reconciled`, `pr.observed`, `pr.closed`, `pr.merged`, `reaction.recorded`, `finding.dismissed` |
| `review_journal` | what an evaluation did | `agent.dispatched`, `review.graded`, `judge.invoked`, `llm.called`, `policy.checked`, `finding.raised`, `finding.resolved`, `finding.rewritten`, `finding.withheld`, `action.taken` |
| `stocktake_journal` | what a periodic review of a repository did | `stocktake.taken`, `stocktake.dispatched`, `stocktake.reviewed`, `stocktake.found`, `stocktake.graded` |
| `policy_journal` | what was done to the policies a server judges by | `policies.deployed`, `policy.calibrated` |

`finding.dismissed` is a person's act on the forge and is the forge's.
`llm.called` is written by the judge about a call it made and is the
review's; what was spent is read from it there. A stocktake is a
review of a range rather than of a pull request, with facts of its own
shape, and has a journal of its own.

Every table has the journal's columns, its two keys to `pull_request`
and `workflow_run`, its indexes under names of its own, and its two
triggers, so a row of any journal is never updated or deleted. On 24
October 2026 the five held 1,394, 10,527, 48,426, 53 and 80 of PMI's
60,480 rows, and 19, 4,360, 5,451, 0 and 36 of GoSource's 9,866.

### Which journal a fact goes to

One map in the shared kernel gives each event type its kind. The
journal adapter writes a fact to its kind's table by that map, and
refuses a type the map does not have. A test holds every event type a
context names to the map, so a new fact is placed when it is written.
The in-memory journal is unchanged.

### Reading

`journal` becomes a view, the union of the five, with the columns the
table had. Every reader of the journal, the review record that
assembles a pull request's history from forge and review facts among
them, reads the view as it read the table. So does PMI's view of real
repositories' facts, and so does the warehouse that reads bronze. A
reader moves to its kind's table when that kind is normalised, and the
view goes when the last reader has moved.

### The script

One script creates the five tables, copies each kind's rows into its
own, drops the `journal` table and creates the view in its name, in
one transaction with the programs stopped. One script and not five,
because the view has to replace the table at the moment the last kind
leaves it, and a half-divided journal under a view is harder to hold
in the head than a whole one. The downgrade creates the table again,
copies the rows back, drops the view and the five.

A row with an event type the map does not have stops the script, so
a fact nobody classified is never lost.

## Rules

1. Every event type belongs to one journal, by the map in the shared
   kernel, and a fact is written to that journal and no other.
2. A journal keeps the journal's shape and its triggers until the
   record that normalises it says otherwise.
3. A reader that reads `journal` reads the view until it moves to the
   journal of the kind it reads.

## Consequences

Each kind of fact can be normalised on its own, by a record of its
own, with readers of the other kinds untouched.

The journal's contract changes in form and not in content: `journal`
is a view with the same columns and the same rows, which the
warehouse's owner reads as before.

A new event type needs a line in the map before the adapter writes it.

Five tables hold what one did, with one index set each.

## Rejected

- *A journal for each writing program.* The programs' types overlap,
  so one fact would be in two tables.
- *Typed tables straight from the journal, with no division.* The
  journal's five kinds would be normalised as one undertaking, and the
  owner wants each normalised on its own.
- *Partitioning `journal` by event type.* It keeps one table and
  routes rows itself, but the event type joins the primary key, and a
  partition cannot be reshaped until it is detached, so normalising a
  kind fights it.
- *Five scripts, one a kind.* Each would leave the journal half
  divided under a view that unions a table with itself.
