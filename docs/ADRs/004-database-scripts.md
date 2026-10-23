# ADR 004: Database scripts

## Status

Proposed, 2026-10-09. Amended, 2026-10-24: a deployment's own tables
are a branch of the package's scripts.

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

A script has a `downgrade` that reverses its change where one is
possible. Where it is not, as when a column is dropped, `downgrade`
raises and its message says why.

### A deployment's own tables

A deployment may keep tables of its own in the same database. It
creates and changes them by scripts of its own, in a directory of its
own, as a branch of the package's scripts: the branch has a label of
the deployment's choosing, and a script that needs a package table
declares `depends_on` the package script that made it. The package's
environment runs both, with the deployment's directory named by the
setting `DATABASE_SCRIPTS`, and records both heads in the one version
table.

A deployment's script may refer to a package table by foreign key,
read one through a view, and write the deployment's rows into one. It
never creates, alters, renames or drops a package table. A package
table is open for extension and closed for modification: the package's
scripts are the only ones that change it, so a package script that
renames a table breaks nothing but the package's own adapters, which
the same pull request changes.

### What a database records

A database records the last script it ran, and the last of each
deployment branch, in the table `bugflow_schema_version`. The name is
the package's own, so a database that also holds another program's
tables, with that program's scripts and its record of them, keeps the
two apart.

A database that records a deployment's branch can be read only by an
environment that has the branch's scripts. `bugflow migrate` without
`DATABASE_SCRIPTS` refuses it, by name of the revision it does not
know.

### Who runs them

`migrations.upgrade(database_url, scripts)` runs the scripts a
database has not run, the package's and those in the directories
`scripts` names. The archive host calls it when it starts, and
`bugflow migrate` is the same call. Any application that needs the
tables may call it. Each takes the directories from
`DATABASE_SCRIPTS`: paths, or package resources such as
`their_package.migrations:versions`, separated by whitespace.

It holds a Postgres advisory lock while it runs, so applications that
start together do not run a script twice.

### A database built another way

The first eight scripts, `s0001` to `s0008`, leave a table or index
that is already there as it is, so they may be run on a database whose
tables were made by an earlier program's scripts. That was the
transition to this record, and every database the package serves has
made it. A later script states its change and does not test for it.

A database built another way after that is stamped at the script that
matches its state before the package's scripts first run, with
Alembic's `stamp` against the package's version table.

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
4. A deployment's scripts are a branch of the package's, and never
   create, alter, rename or drop a package table.
5. A script has a `downgrade` where one is possible, and says why
   where it is not.

## Consequences

A database says which scripts it has run, and bringing it up to date
is one call.

A table's shape is written twice, in a script and in an adapter. The
test holds them together.

Applications start more slowly by the time it takes to take the lock
and find nothing to run.

A deployment with tables of its own runs the package's scripts and its
own in one environment, so a package script that renames a table runs
before any deployment script that refers to the renamed table by
`depends_on`.
