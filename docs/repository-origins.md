# Repository origin associations

Bugflow can inventory retained repository references and associate each
record with an explicit canonical origin. Migration `0008` adds the
association table. It leaves existing records and access behaviour intact.
Ingestion still writes hostless references. Evaluation API reads accept
an optional canonical origin and use explicit associations to select
retained records. This release does not implement repository-key enforcement.

## Canonical form

`RepositoryOrigin` represents `host/owner/name`, independently of the forge
implementation kind. These forms resolve to `forge.example/team/project`:

```
forge.example/team/project
https://forge.example/team/project.git
git@forge.example:team/project.git
ssh://git@forge.example/team/project.git
```

Host case is folded to lowercase. Path case is preserved. A terminal `.git`
is removed. HTTPS port 443 and SSH port 22 are removed; other ports are
preserved, including in the canonical form `forge.example:8443/team/project`.
Two transport endpoints with different non-default ports remain distinct
identities even if an operator knows that they serve the same repository.

The parser accepts two path components and ASCII DNS hosts. It refuses
HTTP, local paths, IPv6 literals, whitespace, query strings, fragments,
percent escapes, trailing slashes and dot path components. HTTPS user
information and SSH passwords are refused. Hostless names have no default
host. The parser does not contact a forge or follow redirects.

## Inventory of persisted references

| Storage | Existing identity | Association treatment |
|---|---|---|
| `journal` | `forge`, `repo`, optional PR number; UUID event id | Map each repository-bearing event by its UUID. Keep its payload and identifier. |
| `pull_request_snapshots` | Hostless `body.ref`; content-derived snapshot id | Map each snapshot id. Keep its body and content hash. |
| `archive_bindings` | Ledger UUID, forge, repo and scope | Map the ledger UUID. Keep the existing binding. |
| Review declarations, enforcement, withholding, spend and period boundaries | Forge and owner/name; some empty scopes mean server-wide | Existing configuration remains hostless. Canonical configuration migration is not in this release. |
| Policy deployments and activation records | Policy repository and commit | Policy-source provenance remains separate from reviewed-repository access. |
| Exchanges and write-ups | Exchange/content ids or workflow/run ids | Resolve repository provenance through the selecting journal event; do not infer it from content ids. |
| Archive events, block puts and indexes | Ledger ids and/or CIDs | Resolve through the ledger association; a CID alone is not repository authority. |

The inventory command emits only retained-record identifiers, forge and
repository names, and association status. It does not emit evidence bodies
or author information. It reads the selected installation; the source
inventory above does not establish what a production installation holds.

## Operator procedure

These commands require direct access to the database named by `DATABASE_URL`.
Restrict that access to administrators. There is no public mapping endpoint.

1. Back up the database. Run `bugflow migrate --check`. Run
   `bugflow migrate`. Existing applications can use the additive schema.
2. Run `bugflow repository-origins > inventory.json`.
3. Establish the origin of each record from deployment records or other
   trusted evidence. Forge kind and owner/name alone are insufficient.
   Leave uncertain records unresolved, including records from mixed hosts.
4. Prepare a JSON array with explicit record ids:

   ```json
   [
     {
       "kind": "snapshot",
       "record_id": "the-retained-snapshot-id",
       "origin": "forge.example/team/project"
     }
   ]
   ```

5. Run `bugflow repository-origins --apply mappings.json`. The command
   validates every mapping before writing. Absent records or conflicting
   origins refuse the whole batch with exit status 2. Repeating an identical
   mapping succeeds. The output is the current inventory, including records
   that remain unresolved. Exit status 0 does not mean all records are mapped.

Kinds are `journal`, `snapshot` and `ledger`. The primary key is kind plus
record id, so equal identifiers in different stores remain independent.
Concurrent mappings cannot replace an association through this command.
The command has no correction or reassignment operation. Review mappings
before applying them. New ingestion remains unresolved until explicitly
mapped. Canonical reads require associations for the journal records and
snapshots they select.

An association states provenance. It grants no permission, creates no
repository-name alias and carries no credential. A changed origin is a
different identity. The later history migration needs a separate explicit
association for access from a new origin; it must not reinterpret this
provenance record as a credential grant. Old-name reuse must not inherit
history through an owner/name match.

## Rollback and remaining migration

Rollback uses the preceding application release while retaining migration
`0008` and its associations. Do not drop or rewrite retained records. Older
applications ignore the additional table. No reverse migration is provided.

Deploy the canonical reader before switching writers. Existing API callers
keep their hostless selection when they omit `origin`. A canonical caller
must use this reader release or later. An older API ignores unknown query
parameters, so directing canonical callers to an older API could return
hostless results. Suspend canonical requests before rolling the API back.
An operator can test reader readiness with mapped records that share a
path on two hosts.

Ingestion still needs to retain the origin. Bindings and declarations need
compatible migration paths. Repository-key activation requires credential
protection and compatible clients in later releases.

## Canonical evaluation reads

Both evaluation endpoints accept `origin=host/owner/name`, or an equivalent
SSH or HTTPS spelling. URL-encode the value as a query parameter. Its
canonical path must match the route's owner and repository. Malformed or
mismatching values return 422 before authorization or evidence selection.
The history response reports the canonical value in `scope.origin`; a
legacy response reports null there.

The reader selects journal events through their explicit associations and
the requested forge and PR numbers. The original event's repository path
can differ, so an explicit historical mapping remains readable without
rewriting the event. Snapshot reads require the same origin, forge and PR
number before transferring their bodies. Exchanges remain selected through
the admitted journal events that reference them.

Contributor access requires author or committer evidence in a snapshot
associated with the requested origin and PR. A contribution on another
host grants nothing. Administrators retain their existing access. The
origin selector itself grants no authority. Legacy requests keep their
existing contributor and administrator rules.

An authorized canonical read returns 409 if matching hostless journal
records remain unresolved, or if a referenced retained snapshot lacks its
association. The journal check covers the selected forge, route path and
PR numbers, and the run for detail requests. This conservative check
refuses partial history while the installation cannot establish which
host those records came from. A mapped record from another origin is
excluded. Absent evaluations retain their 404 response; missing or
out-of-scope snapshots retain the missing-content representation. The
existing event and byte limits still apply to canonical reads.
