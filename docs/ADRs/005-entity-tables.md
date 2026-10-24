# ADR 005: The journal's entities have tables of their own

## Status

Proposed, 2026-10-24.

## Decision

The forge, the repository, the pull request, the workflow and the
workflow run are each a table, with a surrogate key, and a journal row
refers to its pull request and its workflow run by key. The journal's
text columns for them stay.

### The tables

| Table | One row is | Identity, held by a unique constraint |
|---|---|---|
| `forge` | a kind of forge, `github` or `forgejo` | `name` |
| `repository` | a repository on a forge | `forge_id`, `name` |
| `repository_name` | a name a repository has had, and when it was first seen | `repository_id`, `name` |
| `pull_request` | a pull request of a repository | `repository_id`, `number` |
| `workflow` | a workflow, by the id the engine gives it | `name` |
| `workflow_run` | one run of a workflow | `workflow_id`, `name` |

Every table has `id`, a generated integer, as its primary key. A
repository's `name` is the journal's `repo`, `owner/name` with no
host. `workflow.name` is the journal's `workflow_id` and
`workflow_run.name` its `run_id`, since the engine's ids are names
here and `id` is the key.

The run's table is `workflow_run` and not `run`, so that the journal's
reference to it, `workflow_run_id`, does not collide with `run_id`,
the text column the engine's id is in.

A repository has a `origin`, nullable: its canonical origin,
`host/owner/name`, as the repository origins document defines it. The
script that creates the table fills it where every journal row of the
repository that has an associated origin names the same one, and
leaves it null where they disagree or none has one. The association
table of ADR 004's script 0008 stays as the record of each row's
origin, and how the two are reconciled is a later record.

### The journal

The journal gains `pull_request_id`, nullable, since a third of its
rows are about no pull request: reconciliations, deliveries, policy
deployments and archive events. It gains `workflow_run_id`, not null,
since every row names a run. Each is a foreign key. Two indexes serve
the reads that today use the text columns: `pull_request_id` with
`occurred_at`, and `workflow_run_id`.

The text columns `forge`, `repo`, `pr_number`, `workflow_id` and
`run_id` stay. The journal is the contract the warehouse reads and the
view PMI's measurement reads, and the additive rule forbids removing a
column. Once every reader reads the keys, a later record retires the
text.

### Filling the keys

The script creates the five tables from the journal's distinct values,
adds the two columns, fills them, and makes `workflow_run_id` not
null, in one transaction. The journal's triggers reject an update, so
the script disables the two triggers for its transaction and enables
them after. The triggers guard programs. A script that says what it
did, in its docstring and in the version table, is not what they guard
against, and the alternative, a second table filled by copy and
swapped in, rebuilds every index of sixty thousand rows to the same
end.

The script has a downgrade: it drops the two columns and the five
tables.

### Writing

A journal append resolves the entry's forge, repository, pull request,
workflow and run to their rows before it inserts, creating each that
is not there, in the same transaction and under the advisory lock the
adapter already holds for the run. The in-memory journal holds entries
and no keys, and is unchanged. Readers are unchanged by this record.

## Rules

1. A journal row refers to its pull request and its workflow run by
   key, and the keys are filled on every append.
2. An entity's identity is its unique constraint; its key is never
   derived from a name.
3. The journal's text columns are read, and are not removed, until a
   record says every reader reads the keys.

## Consequences

The journal's rows can be joined to their entities without parsing
text, and the typed tables of later records hang off `event_id`, a
pull request and a run by key.

An append does four more statements than it did.

A repository that is renamed keeps its row and gains a row in
`repository_name`, when a later record learns renames from the forge.
Nothing observes a rename yet.

A deployment stops its programs before the script runs, as for the
renames of script 0009, since the script holds the journal for the
length of the fill.

## Rejected

- *Natural keys.* A key on forge and name makes a renamed repository a
  new entity, and this project's policy repository had three names in
  a fortnight.
- *Rebuilding the journal to fill the keys.* The same result at the
  cost of every index, to keep a trigger from the one program it does
  not guard against.
- *Removing the text columns now.* The warehouse and PMI's view read
  them.
- *Resolving the repository origin into the key now.* Two hostless
  names at two hosts are two repositories, and the journal cannot say
  so for every row; the association stays the record until a later
  record reconciles the two.
