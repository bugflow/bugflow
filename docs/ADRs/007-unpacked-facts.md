# ADR 007: A fact's payload is unpacked into a table named for what one row is

## Status

Proposed, 2026-10-24.

## Decision

Each event type's payload becomes a table of its own, with a column
for each of the payload's fields, keyed by the event's id so that it
hangs off the journal row that is its envelope. The journal row keeps
its envelope, the id, the times, the type, the names and the keys of
ADR 005, and the typed table holds the rest. One type at a time, one
script and one adapter change in one pull request under ADR 004, each
tagged and deployed before the next.

### The table

The table is named for what one of its rows is, by the project's
words where it has one: a `finding` for `finding.raised`, a
`judgement` for `judge.invoked`. Where it has none the name says what
happened, as `pull_request_observation` for `pr.observed`. The name
is singular and carries no event type.

Its primary key is `event_id`, a foreign key to the journal of the
fact's kind, so a typed row has exactly one envelope and an envelope
at most one typed row. Nested objects become columns named by their
path, `claims_branch` for `claims.branch`, unless a nested object is
itself a thing with rows, when it becomes a table of its own keyed by
the event and its position.

A field that identifies a person, a login on a forge or an address,
is a column like any other. Who did a thing is a fact the model keeps.
Which columns are one identity, and which identities one person, are
later records with their own evidence, and nothing here forecloses
them.

### What the script does

The script creates the table and fills it from every row of the type
in the journal of its kind, parsing each key set the payload inventory
found for the type. A row whose payload has a key set the script does
not know stops the script, so no fact is unpacked by guess. A field
the inventory found optional is a nullable column; a field found with
two types is parsed to one or stops.

The journal row's `payload` stays as it was. Once every type of a
journal has its table, a record for that journal drops its `payload`
column and the `journal` view reads null for it, and the readers of
that journal's payloads have moved to the typed tables by then.

### Writing and reading

The journal adapter writes the envelope as it does, and in the same
transaction writes the typed row through the type's unpacker, a
function the owning context defines that reads the envelope's payload
and inserts the typed row. The composition hands the adapter the
unpackers of every type that has a table. While the journal's
`payload` column stays, the payload is what the context writes and the
unpacker reads; when the column goes, the context writes the typed
row from its own model and the envelope carries no payload.

A reader of the type moves from the payload to the typed table in the
same pull request as the script, or the pull request says which
readers remain on the payload and why.

## Rules

1. One event type, one typed table, named for what one row is.
2. The typed table's key is the event's id, a foreign key to the
   journal of its kind.
3. The script stops on a payload it does not know how to parse.
4. The journal's `payload` column stays until every type of that
   journal is unpacked.

## Consequences

Every field a fact carries is a column with a name and a type, and
the journal's JSON is read by nothing once each journal's last type
is unpacked.

Twenty-seven tables join the model, one for each event type with
rows, and the archive's three come first.

Each type is its own tag and its own deploy, as the renames and the
keys were.

## Rejected

- *A typed table that keeps a JSONB column beside its columns.* A
  migration for no gain: the shape is as unknown as before.
- *One wide table for a kind of fact.* Its columns would be the union
  of its types' fields, mostly null, and a row would say what it is by
  a type column rather than by its table.
- *Emptying the payload as each type is unpacked.* An update to a
  recorded fact, which the journal's rule forbids and the triggers
  reject; dropping the column once per journal is a schema change
  and not one.
