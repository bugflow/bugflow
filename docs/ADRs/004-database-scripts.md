# ADR 004: Database scripts

## Status

Proposed, 2026-10-09.

## Decision

A database's tables are created and changed by numbered scripts, run
by Alembic. A table is never created or changed any other way.

### The scripts

The scripts are in `src/bugflow/shared/infrastructure/migrations/versions/`,
one file for each change, named `sNNNN_what_it_does.py`. They form one
list for the whole package, since every context's tables are in one
database.

A script states its change in full: the table, its columns, its
indexes. It does not import a table definition from an adapter, so a
script makes the same change whenever it is run.

A script is not edited after it has been merged. A further change is a
further script.

### What a database records

A database records the last script it ran in the table
`bugflow_schema_version`. The name is the package's own, so a database
that also holds another program's tables, with that program's scripts
and its record of them, keeps the two apart.

### Who runs them

`migrations.upgrade(database_url)` runs the scripts a database has not
run. The archive host calls it when it starts. Any application that
needs the tables may call it.

It holds a Postgres advisory lock while it runs, so applications that
start together do not run a script twice.

### The first two scripts

`s0001` creates the archive's tables and `s0002` the journal, with its
indexes and triggers. Both leave a table or index that is already
there as it is, so they may be run on a database that has them.

Later scripts change tables that hold data, and say exactly what they
change.

### Adapters

An adapter still defines the table it reads and writes, to build its
queries. A test brings an empty database up to date with the scripts
and compares it with the adapters' definitions. A column or index in
one and not the other fails it.

## Rules

1. A change to a table is a new script and a matching change to the
   adapter's definition, in one pull request.
2. A script imports nothing from `bugflow`.
3. A merged script is not edited.

## Consequences

A database says which scripts it has run, and bringing it up to date
is one call.

A table's shape is written twice, in a script and in an adapter. The
test holds them together.

Applications start more slowly by the time it takes to take the lock
and find nothing to run.
