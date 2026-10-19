# Repository origin associations

Bugflow can inventory retained repository references and associate each
record with an explicit canonical origin. Migration `0008` adds the
association table. It leaves existing records and access behaviour intact.
New GitHub and HTTPS Forgejo snapshots retain and associate their origin.
Observed evaluation runs associate their journal entries with that origin.
Authenticated deliveries also associate new delivery, dismissal and merge facts.
Closing workflows associate their reaction and closing facts with the
observed source.
Evaluation API reads accept an optional canonical origin and select
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
| `journal` | `forge`, `repo`, optional PR number; UUID event id | Observed evaluations, canonical deliveries and closing workflows associate new entries on insertion. Map historical and remaining independent events by UUID without changing their payloads or identifiers. |
| `pull_request_snapshots` | Hostless `body.ref`, optional `body.origin`; content-derived snapshot id | New canonical snapshots are associated on insertion. Map each historical snapshot id without changing its body or hash. |
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
before applying them. Historical events, independent runs without an
origin assertion and legacy snapshots remain unresolved until explicitly
mapped. Canonical reads require associations
for the journal records and snapshots they select.

An association states provenance. It grants no permission, creates no
repository-name alias and carries no credential. A changed origin is a
different identity. The later history migration needs a separate explicit
association for access from a new origin; it must not reinterpret this
provenance record as a credential grant. Old-name reuse must not inherit
history through an owner/name match.

## Rollback and remaining migration

Retain migration `0008` and its associations on rollback. Do not drop or
rewrite retained records. Older applications ignore the additional table.
No reverse migration is provided. Workers need the drain procedure below
before rollback.

Deploy the canonical reader before switching writers. Existing API callers
keep their hostless selection when they omit `origin`. A canonical caller
must use this reader release or later. An older API ignores unknown query
parameters, so directing canonical callers to an older API could return
hostless results. Suspend canonical requests before rolling the API back.
An operator can test reader readiness with mapped records that share a
path on two hosts.

Independent repository-wide runs still need an origin source. Bindings and
declarations need compatible migration paths. Repository-key activation
requires credential protection and compatible clients in later releases.

## New snapshot ingestion

The GitHub adapter records `github.com/owner/name` from its fixed endpoint.
The Forgejo adapter records the host and port of its configured HTTPS URL.
Forge kind remains separate from origin. A configured HTTPS URL with a path
prefix cannot fit the two-component repository identity and is refused
before fetching content. HTTP Forgejo endpoints retain legacy, unresolved
snapshots. They do not acquire an HTTPS identity by inference.

Every request used to assemble a snapshot refuses redirects, including
commit/file pages and Forgejo's diff. A renamed or transferred repository
must be addressed explicitly by its new name. Webhook administration and
other adapter operations retain their existing redirect behaviour.

A canonical snapshot includes its origin in its content hash, so identical
PR content fetched from two hosts has distinct identifiers. Insertion writes
the body and association in one transaction. A conflicting association
rolls back the insertion. Repeated insertion is idempotent. Historical
snapshots retain their bodies and hashes, even after an explicit mapping.
The snapshot reference passed between existing workflow steps remains a
content handle. The bounded API reader uses its separate origin selector.

Install migration `0008` before starting these writers. Drain review
workflows before replacing workers, and replace the worker set together.
Do not mix old and new workers on the same task queue: older workers discard
snapshot origins when decoding and can compute a different content hash.
Before reverting workers, finish all workflows that consumed canonical
snapshots. Keep stored snapshots and their associations. Older API versions
also discard the body field when displaying content, although the compatible
canonical reader still selects snapshots through the association table.
A new canonical snapshot has a new hash and may cause the same PR content
to be evaluated once more after upgrade.

Snapshot association alone does not make all evaluation history canonical.
Independent journal producers and the declaration/binding transition remain
pending. Do not enable repository-key enforcement on this migration alone.

## Evaluation journal ingestion

Observation asserts the fetched snapshot's origin when recording
`pr.observed`. New entries inherit that origin only within the same
workflow id, run id, forge, repository path and PR number. All retained
entries in that scope must have the same association. An unresolved or
mixed historical scope supplies no implicit origin. A historical mapping
to a different path also supplies no provenance for new writes at the old
path. Entries without a workflow run do not inherit origins.

The writer inserts events and associations in one transaction. PostgreSQL
serializes writers for each scope, including competing first observations.
A known origin assertion refuses an unresolved run or a conflicting origin.
A retry with an explicit origin requires the existing event's scope and
association to match. It never assigns provenance to a previously
unresolved event. Any conflict rolls back the entire batch. Legacy retries
without an assertion retain their existing skip-on-duplicate behaviour.
Event ids, payloads and the journal schema remain unchanged. The domain
entry's `origin` and `origin_asserted` fields are metadata, not journal
columns. An observation with an unknown source origin may start a legacy
run. It cannot inherit or replace a known origin on a retry.

Publishing and checkout-review reuse select historical evidence through
the current evaluation's origin. Findings, dismissals and verdicts from
other origins or unresolved records are excluded. This prevents an old
finding or verdict from being copied into a new origin's evaluation.
A current run with only some entries mapped is refused. Before upgrading,
explicitly map the historical records that should remain eligible for
carry-forward and verdict reuse. Legacy runs with no known origin retain
their existing review behaviour.

Run migration `0008` before using this writer. Drain old workflows before
upgrading or reverting workers. An upgraded observation cannot establish
provenance retrospectively for an already unresolved run. Reverting writers
leaves subsequent journal events unresolved and can cause canonical reads
to return 409. Retained associations remain intact.

A newly observed evaluation can be read by its canonical origin without a
manual per-event mapping. Independent repository-wide records still need
their own origin source. A repository history request can therefore return
409 while a detail request for the fully associated evaluation succeeds. Bindings, declarations and
repository-key enforcement still need their later migration steps.

## Delivery ingestion

After signature verification, the GitHub ingress route assigns the fixed
`github.com` endpoint. The Forgejo route uses `FORGEJO_URL`; configure the
same endpoint on ingress, workers and pollers. The webhook secret must belong
to the forge configured for that route. Ordinary payload repository URLs
cannot override this setting. HTTP or absent Forgejo settings leave new
records unresolved. Unsupported HTTPS path prefixes or credentials in the
endpoint refuse ingress startup. Events without a repository remain unresolved.

The poller records the endpoint of each successful PR or comment listing.
All listing pages refuse redirects. Its signed webhook body carries this
origin in `_bugflow_origin`. The ingress reads that field only for delivery
ids with the existing `poll-` prefix, and rejects a non-null origin that
differs from its configured endpoint. Missing or null metadata remains
explicitly unresolved; it does not acquire the ingress's configured host.
Poll coverage checks with a known origin count only deliveries associated
with that same origin. Legacy calls without an origin retain hostless checks.

Delivery, dismissal and merge facts assert their source in the journal's
existing atomic append. Their ids and payloads stay unchanged. A duplicate
delivery still returns `duplicate` before starting another evaluation and
never assigns an origin to an existing unresolved event. Delivery ids remain
forge-scoped: reuse of a retained id on another host remains a duplicate,
not a new delivery or a reassignment. Origins do not make operational
workflow ids or delivery ids host-aware in this release.

An unresolved or conflicting workflow scope returns HTTP 409 and retains
its existing records. Workflow signalling still precedes journal append,
so a rejected append can follow a successful signal. Retrying does not
repair the scope: inspect and explicitly map retained records where the
evidence supports the mapping. Unknown-source deliveries cannot inherit a
known run's origin.

Install migration `0008` and drain existing workflows before replacing
ingress, pollers and workers together. An older poller omits the source
metadata; its deliveries stay unresolved and can conflict with a canonical
run. An older ingress discards the poller's metadata. On rollback, retain
associations; subsequent unresolved records can make canonical history
return 409. Repository-wide review runs still need provenance, and
repository-key access remains disabled.

## Closing workflow ingestion

The closing-state read supplies the source origin: GitHub's fixed endpoint
or the configured HTTPS Forgejo endpoint. HTTP Forgejo remains unresolved.
Closing-state and reaction requests refuse redirects. Unsupported HTTPS
path prefixes refuse the closing-state read before contacting the forge.
The worker passes that source into the review context without changing
workflow input or event identifiers.

Before reading reactions, collection checks that the observed origin
agrees with every existing event in the same workflow run, forge,
repository path and PR number. A known source refuses unresolved or
conflicting records in that scope. An unknown source cannot inherit a
known run's origin. These provenance errors stop the activity without
automatic retries; inspect the scope and repair mappings explicitly where
evidence supports them before rerunning the workflow.

For a canonical source, collection selects posted comments, reviewer
attribution and the last published evaluation's outstanding findings only
from records associated with that origin. Foreign and unresolved history
cannot be copied into the closing record. Map older review evidence before
upgrading if it should remain eligible for collection. An unresolved source
retains legacy history selection and produces unresolved closing records.

All reaction and closing facts assert the observed source in one journal
append. Retrying an unresolved closing event with a newly known source
refuses reassociation. Retrying the same source preserves existing event
identifiers and associations. The journal checks provenance again at append,
so a concurrent conflicting writer cannot commit a mixed batch.

Migration `0008` and the coordinated drain and worker replacement above
remain required. Reverting to older closing workers restores hostless
history selection, so suspend closing collection before rollback while
retaining all stored associations. Repository-wide producers, declarations
and ledger bindings still need their migration steps. This release does
not enable repository-key enforcement.

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
