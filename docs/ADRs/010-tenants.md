# ADR 010: Tenants

## Status

Proposed, 2026-11-04. Amended, 2026-11-10: ADR 011 lets more than one
tenant compose the review part, each with a policy deployment in force
of its own.

## Context

A deployment is one server on one host (`docs/deploying.md`). It
builds one image from the package and runs one worker, in Temporal's
`default` namespace, with one ingress whose routes and pipeline are
shaped for pull requests. A program built on the package adds parts to
that same worker and ingress process through `WorkerParts` and
`IngressParts`. pmi-bugflow is that program: the package's review and
archive parts plus its own, in one process, on one queue, in one
namespace. pmi-bugflow is also where the package came from, and
milestone M8 of its `todo.org` moves the rest of the product code into
the package.

gs-bugflow is the second server. Its first worker beside the review
product is gs-crm's (gs-crm `docs/workflow-worker.md`; gs-gs/gs-bugflow
#43 and #44). That design gives the worker its own image on GHCR, the
namespace `gs-crm`, a dependency on `temporalio` alone, and an ingress
of its own beside the worker. GoSource has five areas of
responsibility, each in a repository with its own CI, and each is to
own workflows: GMC, business development, delivery assurance, business
management and capability assurance. Workers partition as the
organisation does.

Three things stand between the package and that shape. Nothing creates
a namespace: `temporalio/auto-setup` makes `default` and the templates
set no other. The ingress has one client, one secret and fixed routes,
and its pipeline (`Delivery`, `ReceiveDeliveryUseCase`,
`PullRequestRef`, the starter) knows only pull requests. And nothing
says what a worker owes the platform: the settings it reads, how it
fails, what it serves, what it emits. gs-crm's worker answered each
for itself, in about 170 lines, and the next tenant would answer them
again.

## Decision

### Words

A server is one deployment of the package for one organisation, as
pmi-bugflow's ADR-078 has it. A server is a platform and its tenants.

The platform is Temporal, Postgres, LiteLLM, the ingress, the front
door, the migrate command and provisioning. The ingress is the one
program on it from the package.

A tenant is an area of responsibility that owns workflows. A tenant has
a Temporal namespace named for it, a worker image that its own
repository's CI builds and publishes, its own settings and secrets, and
its own task queues. A server runs one worker container per tenant,
pinned by image tag, moved by commit. A tenant may run programs beside
its worker: an API, an MCP server, a poller, the archive host.

The platform's repository is the parent area's, and it deploys the
platform and every tenant. At GoSource that is GMC's, `gs-bugflow`.
GMC's own workflows, when it has them, run from that repository in a
namespace of GMC's, `gmc`. Each other area has a repository of its own,
named for the server and the area, `gs-bugflow-bd`, `gs-bugflow-ca`,
`gs-bugflow-bm` and `gs-bugflow-da`, and each publishes an image of
the same name. What a tenant's worker imports is its own affair: one
may compose the package's parts and another depend on `temporalio`
alone, and the platform treats them alike.

### The package's products are tenants' parts

The package's review workflows and stocktake, and its archive host and
archive index, are parts in the sense of ADR 002: a tenant composes
them into its worker with `WorkerParts`, and runs their programs beside
it. At PMI both compose into PMI's worker. At GoSource review and the
stocktake compose into capability assurance's, because quality
assurance of delivery is that area's, and the archive into business
management's, because records and compliance are that area's. No
platform program runs either, and a server with no tenant that
composes review reviews nothing. The code of both stays in the
package: ownership of the free software and responsibility for running
an organisation's instance are different things.

Each tenant has a composition root of its own, in its own repository:
a program that names the parts it serves and calls the package's
`worker.run` with them, as pmi-bugflow's `app/worker.py` does. The
package's `bugflow worker` command keeps its present composition, the
archive index and review together, for a server with one tenant.

The two contexts are already apart in the package. `archive` imports
no other context and nothing else imports it, which import-linter
enforces; the archive host is its own program with its own settings;
`archive_index.parts` is a `WorkerParts` of its own; and the archive
has no webhooks, since gardens reach it over the remote archive
protocol. Splitting them into two tenants is composition and
deployment, not code.

### The front door

The front door is the proxy and its routes, and it belongs to the
platform. A route names a service, never the tenant that runs it, and
a service that moves between tenants keeps its route. A person or a
garden that uses a service does not know, and need not know, which
area is responsible for it. GoSource's routes today, the server's
host name for the ingress, the API's, and the archive's wildcard, stay
as they are when the archive host becomes business management's; the
ledgers that GMC's and delivery assurance's `.clanka/config.yml` name
go on resolving.

### The tenant contract

A tenant owes the platform a contract, and nothing else: no import, no
shared library, no language. The contract is a document in the
platform's repository and a conformance harness that proves a tenant
image keeps it.

| Clause | What the tenant does | How it is proved |
|---|---|---|
| Settings | Reads `TEMPORAL_ADDRESS`, `TEMPORAL_NAMESPACE`, `TEMPORAL_TASK_QUEUE`, the LiteLLM address and key, and the OTLP endpoint, by those names | The register renders them |
| Fail fast | Stops before connecting when a setting is missing or bad, and names the setting on stderr, never its value | Run the image without each setting; expect exit and the name |
| Receive | Serves a workflow `Receive` on its receive queue, taking a JSON payload of headers and body under Temporal's default data converter | Signal a sample delivery; see the run start |
| Shutdown | Drains and exits on SIGTERM | Send it; expect exit within the grace period |
| Telemetry | Sends OTLP traces to the platform's collector and writes log lines as JSON with the named fields | Capture one trace and one line |
| Image | Publishes a tag per release, runs as a non-root user, has one entrypoint | Inspect the image |
| Layering | Keeps use cases free of `temporalio`; workflows and activities are shells around use cases; one composition root | import-linter contracts in the template; a worker gnome's policies, judged at review |

The harness runs in the tenant's CI against the tenant's image and
Temporal's dev server. It is shared at build time only; a tenant that
passes it owes the platform nothing at run time, and a tenant in
another language passes it the same way.

The payload crosses the ingress boundary under the default JSON
converter. The package's programs use the pydantic converter among
themselves; a tenant may use any converter inside its own namespace.

The layering rules, ADR 001 to 003, the settings rule and the receive
convention, are also a worker gnome's doctrine and policies. Each
tenant's repository is a watched repository of the organisation's
server, so review judges its pull requests against them, and a garden
that declares the gnome installs its skills for whoever writes a
worker.

Business development's worker is the template the next tenant copies. A tenant may
import the package's `TemporalSettings` or `WorkerParts` if it wants
them; this record makes no promise about them.

### The ingress routes by namespace

A server has one ingress. Its route is `POST /hooks/{namespace}/{source}`.
It holds one secret per namespace and source, with a previous secret
for rotation, verifies the signature by the source's scheme (GitHub's
`X-Hub-Signature-256`, Forgejo's `X-Forgejo-Signature`, Standard
Webhooks for a managed agent's completion), and signals-with-start the
workflow `Receive` in that namespace, on the tenant's receive queue,
with the raw body and headers. The workflow id is
`receive/{source}/{delivery id}`, so a redelivery joins the run
already started: Temporal's own start-once replaces the journal check
the ingress makes today. The ingress reads no body. It opens one
client per namespace at start, from the tenant list in its settings.

The pull-request pipeline moves from the ingress into the review part.
The review part's `Receive` workflow normalises a forge body, checks
the journal for a pull-request event it has seen, and signals the
pull-request workflow, as the ingress does today. The managed agent's
completion goes the same way. `bugflow webhooks` registers hooks at
the tenant's path, and the poller posts to it. gs-crm's application
posts to `/hooks/business-development/gs-crm`, signed with that
source's secret.

### Provisioning

The platform creates each tenant's namespace before its worker starts,
in the pattern `migrate` already follows: a one-shot service,
`namespaces`, from `temporalio/admin-tools` at the server's version,
runs `temporal operator namespace create` for each tenant once
`temporal` is healthy, and each tenant's worker waits on it with
`condition: service_completed_successfully`. Alembic is idempotent by
design; this step is made so, by describing before creating. No
worker runs in `default`.

### The tenant list

The deployment's register is the one source of the tenant list. On
the pocketmoneyindustries platform that is the server's entry in
platform-cmdb's `estate.json`, which already names the ref to deploy,
the routes and the settings; in the standalone it is `settings.yml`.
Each tenant's entry names its namespace, its image and tag, its
sources and the vault keys of their secrets. The render reads it three
times: into the ingress's settings, into the `namespaces` service's
arguments, and into one compose entry per tenant. The compose file is
rendered output, never the source.

### Data

A tenant's records are its own. A tenant that shares the server's
Postgres keeps its tables as a branch of the package's scripts (ADR
004), or keeps a database of its own, or keeps none. No platform
program reads a tenant's records. The review part's journal, API
routes and MCP tools remain the review part's, so a record that names
a run by workflow id and run id alone stays as it is. The archives
that other areas' gardens keep are business management's to hold and
theirs to read, through the remote archive protocol, as now.

The tenants that compose the package's parts share one database. The
package's scripts are one chain, `s0001`, the archive tables, through
the review's, and `migrate` runs it once, for both. Two archive tables
lean on the shared kernel, `archive_binding` on `repository_associations`
for a ledger's origin and the archive's facts on the journal, so the
two tenants take the package at one pin and move it together. The
chain is not split into branches by context; that would be an
amendment to ADR 004, and nothing here needs it.

### Cross-tenant work

None is designed. A tenant that needs another tenant's workflow calls
it through Temporal Nexus, when the need arises.

## Rules

- A namespace takes its tenant's canonical name, `capability-assurance`.
  An informal name stays in prose.
- `default` holds no worker.
- The tenant's repository builds and publishes the tenant's worker
  image. The server pins it by tag and moves the pin by commit.
- A tenant keeps the tenant contract, and its CI runs the conformance
  harness. The platform asks nothing else of it.
- A tenant's composition root is in the tenant's repository. The
  package's commands compose nothing for a tenant.
- The platform's repository is the parent area's. A child area's
  repository and image are named for the server and the area.
- Tenants that compose the package's parts share one database and one
  pin of the package.
- The ingress reads no body. A tenant's `Receive` workflow normalises.
- A payload that crosses the ingress boundary is JSON under the
  default data converter.
- A platform program holds no tenant's credential. A tenant's worker
  holds no other tenant's.
- A route names a service, never its tenant. A service that changes
  tenant keeps its route.
- Each tenant has its own LiteLLM key and rate budget.

## Consequences

The first step is the split of GoSource's one worker into two tenants.
`gs-bugflow-ca` holds the composition root that serves review and the
stocktake, with the API, the poller and the MCP server beside it, in
the namespace `capability-assurance`. `gs-bugflow-bm` holds the
composition root that serves the archive index, with the archive host
beside it, in the namespace `business-management`. Each publishes its
image, and `gs-bugflow` pulls both. It needs the two repositories, the
`namespaces` service, two tenant entries in the register, one drain
for review's pull-request runs, and two changes in the package:
the archive host reads `TemporalSettings` in place of its own
`TemporalAddress`, so the host and the index share one setting and the
host starts the index in business management's namespace; and `bugflow
declare --archive`, which binds a ledger to a repository, is run
against the shared database by either tenant. It needs nothing from
the ingress and nothing from gs-crm, and it proves provisioning, the
register layout and the drain before another area's worker arrives.

gs-bugflow becomes a platform composition plus one compose entry per
tenant, each with its own env template, vault prefix and image pin,
and gains a GHCR pull credential and a provisioning step.
gs-gs/gs-bugflow#43 becomes the entry for business development's
tenant, `gs-bugflow-bd`, in the namespace `business-development`,
pulling `ghcr.io/gs-gs/gs-bugflow-bd`. Decision 1 of gs-crm's
`docs/workflow-worker.md` changes with it: the worker's code moves
from gs-crm's `workflow/` to that repository, since the tenant is the
area and gs-crm is one of its products. The empty worker on gs-crm's
unmerged branch moves there rather than merging where it is. #44
changes from running gs-crm's ingress to adding the tenant's namespace
and secret to the platform's, and decision 5 changes with it. Decision
7, a dependency on `temporalio` alone, stands, and the worker gains a
`Receive` workflow and the conformance harness in its CI.

The platform's repository gains the contract document, the harness and
the worker gnome. The package changes only at the ingress; nothing in
it is extracted or republished for tenants.

The archive host leaves the platform composition. Its compose entry,
its bucket, its credential and its `bugflow_archive_*` settings move to
business management's tenant entry in the register, and the archive
index runs in the `business-management` namespace. Business
management's first tenant entry is the archive alone, with no workflow
of its own beyond the index. `gs-bugflow-bm` holds the composition
root and the archive's configuration: the ledgers kept, the bucket,
retention and who may read which. The roles
`bugflow-archive-reader` and `bugflow-archive-writer` and the archive's
route stay as they are, under the front-door rule.

With review and the archive both tenants' parts, the platform holds no
product program but the ingress. A deployment is then a tenancy with
N tenants at every server: GoSource's five, PMI's one composing both
sets of parts, bugflow.org's one composing review.

pmi-bugflow becomes PMI's tenant. Its namespace is named, and the
platform programs separate from its worker in compose. Its joins with
the review part (the lens grader, the `real_journal` spend view, the
corpus refresh) stay in process, as parts of one tenant worker, and M8
continues as written. The corpus refresh leaves `IngressParts` and
starts from a `Receive` in PMI's parts.

The review part leaves `default` once at each server: PMI's,
GoSource's and bugflow.org. `PullRequestWorkflow` lives for days and
Temporal 1.25 does not pin workers, so each server drains before the
move, as a scheduled deployment. A new tenant's namespace starts
empty and needs none.

The tenant list, and with it each tenant's image pin, lives in the
hosting platform's register, so it moves when the hosting moves to
GoSource.

Five workers and the platform on gs-dev-cg, 4 vCPU and 8 GB shared
with the identity provider, gs-mastermind and monitoring, with no
container limits, is sized before the second tenant runs. gs-crm's
design places bugflow on AWS; capability assurance's canon has no
hosting plan beyond the handover to GoSource's hosting. The two are
reconciled before that handover changes shape.

## Open questions

1. Whether the review part's API stays the one program it is or each
   tenant mounts its own routes. Today a server built on the package
   mounts `policy_deployment_routes`.
2. Whether a tenant's image tag is written in the register by hand,
   as bugflow's ref is, or read from a manifest the tenant's repository
   publishes at each release.
3. Whether `Receive` is the one convention or the ingress also signals
   an existing workflow by an id taken from a header.
4. The shape of a tenant's entry in `estate.json`, which this draft
   has not read.
5. Where the platform composition, the contract, the harness and the
   gnome live: in the package's `deployments/`, as the composition
   does now, or in a repository of their own that gs-bugflow and
   pmi-bugflow both take. With the archive a tenant's, the package has
   nothing on the platform but the ingress.
6. Which fields the telemetry clause names, and the grace period the
   shutdown clause allows.
