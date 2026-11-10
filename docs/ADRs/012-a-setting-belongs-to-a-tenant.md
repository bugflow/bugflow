# ADR 012: A gnome's setting belongs to a tenant

## Status

Proposed, 2026-11-10.

## Context

ADR 011 gives each tenant a policy deployment in force of its own, and
holds that a reviewer's id is one tenant's on a server. A setting was
keyed by repository and gnome, so a setting of `prose` would switch on
both tenants' prose at once and the settings page could not say whose
a column was; a reviewer's commit status is named by its id, so two
reviewers of one id would write one status; and the ingress routed a
runner's completion by the reviewer's id. Deploying refused a
deployment that holds a reviewer another tenant's deployment in force
holds.

The rule comes from the shape of three records. Each worker's facts are
journalled under its own workflow run, in its own namespace, stamped
with its own deployment, so two workers reviewing one repository with
reviewers of one id corrupt nothing. The refusal reaches into another
tenant's binding: the website gnome had to leave capability assurance's
binding before business development's could hold it.

## Decision

A gnome's setting belongs to a tenant, and the rule that a reviewer's
id is one tenant's is lifted.

### The record

`gnome_setting` gains `tenant` in its key, and the typed table
`gnome_setting_change` gains the column; the `gnome.set` fact names the
tenant. Every row held before the script is `default`'s, and the column
keeps that default, so a program older than the column writes rows that
are still that tenant's.

### The qualified name

One tenant's gnome is named apart from another's of the same id by its
qualified name: the gnome's id for the default tenant, and `tenant/id`
for any other. A tenant's name holds no slash, so the name reads back
as the tenant up to the first slash and the gnome after it. The
settings page keys each column by it, `bugflow settings` prints it, and
a reviewer sets its commit status under it, so two tenants' reviewers
of one id set two statuses on a commit. A server with one tenant sees
the id alone.

### Who reads what

A worker reads its own tenant's settings and no other's. The ingress
hands a delivery to each tenant whose setting judges the repository. A
runner's completion is offered to each tenant that holds the reviewer's
id, in tenant order, until one answers that it was waiting: a workflow
run's id is in one namespace alone, and a starter answers "unable" for
a run its namespace does not hold.

The body of `PUT /api/settings/{forge}/{owner}/{repo}/{gnome}` names
the tenant, and `bugflow set` takes `--tenant`. Unnamed, the tenant is
the one whose deployment in force holds the gnome, else the one whose
setting of the gnome the repository has, which is how a gnome a
deployment dropped is switched off, else `default`. Where two tenants
hold the gnome and none is named, the setting is refused. The settings
page names it.

Deploying still refuses a deployment that gives a layer a cadence
another tenant's deployment in force gives it otherwise, since a
boundary is declared on the layer's name with no tenant. The check that
a deployment drops no profile a setting names passes over the other
tenants' settings.

## Rules

- A setting names its tenant. A server with one tenant names `default`.
- Two tenants may hold a reviewer of one id.
- Wherever every tenant's gnomes are named together, and in the commit
  status a reviewer sets, another tenant's gnome is named `tenant/id`
  and the default tenant's by its id.
- A worker reads its own tenant's settings.
- A layer's name has one cadence on a server (ADR 011).

## Consequences

At GoSource, business development's binding may pin the website gnome
while capability assurance's binding still holds it. The two stand
apart on the settings page as `website` and
`business-development/website`, and each tenant's setting switches on
its own.

The label a pull request carries is decided by each worker from its own
gnomes' verdicts, as ADR 011 records: two tenants whose gnomes publish
on one repository each write it, and the last to publish stands.

A commit status set by a reviewer of a tenant other than `default` is
named `tenant/id`. No server runs a second tenant yet, so no status
anyone reads is renamed.

PMI's server and the example change nothing: their settings are
`default`'s, and the page, the command and the forge name each gnome by
its id.

## Rejected

- *Keeping the rule.* It is a rule about three records, which this
  record changes, and it decided what another tenant's binding may
  pin.
- *A tenant column on the journal, to route a completion.* The
  namespace that holds the workflow run routes it: the ingress offers
  the completion to each tenant that holds the reviewer, and a run's
  id is in one namespace.
- *Naming the default tenant's statuses `default/id` too.* A server
  with one tenant would see every status renamed, and a branch
  protection that names one would need changing.
