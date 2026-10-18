# Repository origin associations

Bugflow can inventory retained repository references and associate each
record with an explicit canonical origin. Migration `0008` adds the
association table. It leaves existing records and access behaviour intact.
Ingestion and API reads still use the existing hostless references. This
release does not enable repository keys or canonical history queries.

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

1. Back up the database, then run `bugflow migrate --check` and
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
mapped; this inventory is preparation for the reader/writer migration.

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

Before canonical identities can select review history or archive access,
ingestion must retain the origin, readers must resolve historical records,
and bindings and declarations need compatible migration paths. Existing
API callers keep their current behaviour in this release. Canonical reads
must distinguish an absent record from an unresolved association and check
authority independently of historical lookup. Repository-key activation
requires credential protection and compatible clients in later releases.
