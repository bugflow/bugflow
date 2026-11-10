# ADR 011: A policy deployment belongs to a tenant

## Status

Proposed, 2026-11-10. Amended, 2026-11-10: ADR 012 gives each setting
a tenant and lifts the rule that a reviewer's id is one tenant's.

## Context

ADR 010 makes a server a platform and its tenants, and places the
review part in one tenant's worker: at GoSource, capability
assurance's. Business development's tenant runs an empty worker, and
the website gnome, which is business development's standard, is
judged by capability assurance's worker because that is the only
worker that reviews.

A second worker composing the review part cannot run beside the first
on one database. The deployment in force is the latest row of
`policy_deployment_in_force`, one for the whole server, and every
program reads it: the worker builds its reviewers from it, the ingress
takes its layers and settling windows from it, the API checks each
setting against it, and `set` and `declare` read it. Two workers would
read one deployment and review every pull request twice.

The other records already hold for several workers. A gnome's setting
is keyed by repository and gnome. A boundary is keyed by repository and
layer name. Workflows and schedules live in each worker's own
namespace.

## Decision

A policy deployment belongs to a tenant, and each tenant has a
deployment in force of its own. A server with one tenant names none:
its tenant is `default`, and nothing about it changes.

### The record

`policy_deployment`, `policy_deployment_file` and
`policy_deployment_in_force` gain `tenant`, in the key of the first two
and the foreign keys of the last two, so one commit of a binding may be
held for two tenants and each tenant's deployment in force is read
apart. The typed table `policy_deploy` gains it too, and the
`policies.deployed` fact names it. Every row held before the script is
`default`'s, and the column keeps that default, so a program older than
the column writes rows that are still that tenant's.

A tenant's name is lower case letters, digits and hyphens, the shape of
the Temporal namespace a tenant is named for under ADR 010.

### Who reads what

The worker reads the setting `TENANT`, and builds its reviewers from
that tenant's deployment in force. It reads the settings of the gnomes
that deployment holds and no other tenant's: another tenant's gnome on
the same repository is that tenant's worker's to judge, publish and
schedule. It stops when its own tenant's deployment changes and not
when another's does.

The ingress is one for the server. Its own tenant is `TENANT`, in its
own namespace and on its own task queue; `TENANTS` lists the others as
`tenant=namespace/task-queue`. It reads every tenant's deployment in
force, holds a client and a starter for each, and hands a delivery to
the workflow of each tenant whose gnome judges the repository, read
from the settings when the delivery arrives. A repository no tenant's
gnome judges is handed to the ingress's own tenant, as before. A
runner's completion goes to the tenant whose reviewer was dispatched.
It stops when any tenant's deployment changes, and says which.

The API deploys for the tenant the body names. `TENANT_DEPLOYERS` names
the client that deploys each tenant's policies, so one tenant's
pipeline cannot put a deployment in force for another; a tenant not
named takes any caller with the deployer role. `bugflow deploy-policies`
and `install-policies` take `--tenant`. The settings page lists every
tenant's gnomes together, each named for its tenant, and each tenant's
deployment. `set` and `declare` read every tenant's deployment.

### What one tenant may not take from another

A reviewer's id is one tenant's on a server, because a setting names
the reviewer and not its tenant. A layer's name has one cadence on a
server, because a boundary is declared on the name. Deploying refuses
a deployment that holds a reviewer another tenant's deployment in force
holds, or gives a layer a cadence another tenant's gives it otherwise.
The check that a deployment drops no profile a setting names passes
over the settings of other tenants' gnomes, which are theirs to keep.

## Rules

- Each tenant has a deployment in force of its own, named by its
  tenant. A server with one tenant names `default`.
- A worker reviews by its own tenant's deployment and reads the
  settings of the gnomes it holds, and no other tenant's.
- The ingress hands a delivery to each tenant whose gnome judges the
  repository, in that tenant's namespace.
- A reviewer's id is one tenant's on a server. A layer's name has one
  cadence on a server.
- A tenant's pipeline deploys that tenant's policies and nobody
  else's.

## Consequences

At GoSource, business development's tenant composes the review part
as capability assurance's does, with a binding of its own that pins
the website gnome, in the one database and with no further container.
The website gnome leaves capability assurance's binding first, since
one tenant's deployment may not hold what another's holds.

PMI's server and the example change nothing: their one tenant is
`default`, the migration carries what they hold to it, and no setting
is added.

The label a pull request carries is decided by each worker from its own
gnomes' verdicts. Two tenants whose gnomes both publish on one
repository each write it from their own view, and the last to publish
stands. Setting one tenant's gnomes to publish on a repository is the
arrangement this record provides for; a label decided across tenants is
left for a later record.

Allowances, cadence boundaries and repository boundaries stay the
server's, as they are. The journal stamps each fact with the deployment
it was written under by repository and commit, which names the tenant
too while each tenant has a binding of its own.

ADR 010's plan for the ingress, one route for each namespace and source
with the pull-request pipeline moved into the review part, stands. This
record changes where a delivery is handed, not how it arrives.

## Rejected

- *A second review service for the second tenant: its own database,
  ingress, API and poller.* It reviews with no change to the package,
  and costs five containers and two of every setting.
- *A tenant table that each worker registers itself in, read by the
  ingress.* It saves a setting and leaves a row behind when a worker
  goes, which the ingress would go on handing deliveries to. ADR 010
  puts the tenant list in the deployment's register, and `TENANTS` is
  that list rendered.
- *Naming the tenant by `TEMPORAL_NAMESPACE`.* A server whose one
  worker runs in a namespace of its own would then find no deployment
  in force after the migration, and would have to be sent its binding
  again before it reviewed. A setting of its own, defaulting to
  `default`, changes nothing for a server with one tenant.
