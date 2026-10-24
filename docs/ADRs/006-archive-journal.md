# ADR 006: The archive host keeps a journal of its own

## Status

Proposed, 2026-10-24.

## Decision

The archive host's facts, `archive.sealed`, `archive.bound` and
`archive.refused`, move from the journal to a table of their own,
`archive_journal`, of the journal's shape and under the journal's
rule. No other fact moves by this record.

### Why the archive and only the archive

The plan behind this record proposed a journal for each program that
writes one, on the premise that each program's event types are
disjoint. They are not. The forge context's use cases run in the
worker as well as in the ingress, so `pr.observed` and `judge.invoked`
are written by both, `pr.merged` by the ingress on a delivery and by
the worker at a stocktake, and `webhook.reconciled` by the webhooks
command in the worker's container. Splitting those by program would
divide one fact's rows between two tables by who happened to write
them.

The archive's three facts are the exception. Only the archive host's
two use cases write them, nothing in the package reads them from the
journal, nothing in PMI's code does, and they are about no pull
request. The keeper's own record of each event is the `archive_event`
table beside them. They are the one clean seam, and the rest of the
journal is divided by the typed tables of a later record, which take a
fact's rows by its type rather than its writer.

On 24 October 2026 the archive's facts were 1,394 of PMI's 60,480
rows and 19 of GoSource's 9,866.

### The table

`archive_journal` has the journal's columns, its keys to
`workflow_run` and `pull_request`, its indexes under its own names,
and its two triggers, so a row of it is never updated or deleted
either. It is created by a script that copies the archive's rows from
the journal and then deletes them there, with the journal's triggers
disabled for the script's transaction, as the keys were filled under
ADR 005. The script's docstring and the version table say what it
did.

### Writing and reading

The archive host's recording service writes to `archive_journal`. The
journal adapter takes the table it writes to, and the archive host
composes it with this one; every other program composes it as before.
The in-memory journal is unchanged.

Nothing in the package reads the archive's facts from the journal, so
no reader changes. PMI's view of the journal, which reads real
repositories' facts, loses the archive's rows and reads nothing of
them today. The warehouse that reads the journal as bronze reads the
archive's facts from the new table from then on, which its owner
changes in it.

### Downgrade

The script's downgrade copies the rows back under disabled triggers
and drops the table.

## Rules

1. The archive host writes its facts to `archive_journal` and to
   nothing else.
2. A journal table, whichever program's, keeps the journal's shape and
   its triggers.
3. A fact's rows are not divided between tables by which program wrote
   them.

## Consequences

The journal holds review and forge facts, and the archive's are apart.
A program that reads one need not know the other's shape of payload.

The journal's contract changes once, in that rows of three types leave
it; a reader that counted them there counts them in `archive_journal`.

The split by writer the plan foresaw for the rest of the journal does
not happen. The typed tables of the unpacking record divide the
journal by type instead.

## Rejected

- *A journal for each writing program.* The programs' types overlap,
  so one fact would be in two tables.
- *A journal for each context.* `pr.observed` and `judge.invoked` are
  written by three contexts' use cases.
- *A union view over the journals for the warehouse.* A view is a
  reader the contract must then keep, and the warehouse's owner can
  read two tables.
