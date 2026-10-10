# Deploying a server

## What a deployment is

A deployment is one server on one host: the programs of this
repository, and the Postgres, Temporal and model proxy they run on,
brought up together by Docker Compose.

| Service | Is | Needs before it starts |
|---|---|---|
| `postgres` | The database: the journal, the policy deployments and Temporal's own records | Its settings |
| `temporal` | The workflow engine | `postgres` healthy |
| `temporal-ui` | The workflow console | `temporal` healthy |
| `litellm` | The proxy models are called through | Its settings |
| `migrate` | `bugflow migrate`, which brings the database up to date and exits | `postgres` healthy |
| `worker` | `bugflow worker`, which reviews pull requests | `temporal`, `postgres` and `litellm` healthy, `migrate` finished |
| `ingress` | The server that receives a forge's webhooks | `temporal` and `postgres` healthy, `migrate` finished |
| `api` | The server a policy repository's pipeline deploys policies to | `postgres` healthy, `migrate` finished, an identity provider in its settings |
| `poller` | `bugflow poll`, which stands in for webhooks. Started only when asked for | `ingress` healthy |
| `webhooks` | `bugflow webhooks`, which registers webhooks and exits. Run only when asked for | `migrate` finished |

Three kinds of file make a deployment:

- `deployments/{environment}/docker-compose.yml`, the composition, and
  the `.env` beside it, which names the client, the solution and the
  environment.
- `deployments/env/*.env.j2`, a template of each service's settings.
  A deployer renders them into `env/` at the root of the repository,
  one file for each service. The composition reads them from there.
- `Dockerfile`, which builds the one image every program runs from,
  and `litellm/config.yaml`, the proxy's list of model roles.

`deployments/example/` is the composition this repository is tested
against.

## A local run

    make env
    make up

`make env` copies `.env.example` to `.env`, generates a Postgres
password, a webhook secret and a proxy key in it, and renders the
templates from it into `env/`. Fill in the rest of `.env` and run
`make env` again to render the change. `make up` creates the edge
network if the host has none and brings the composition up. `make
down` stops it and keeps the database.

No service publishes a port on the host. To call one, run the call in
a container:

    docker compose -f deployments/example/docker-compose.yml \
        exec ingress python -c \
        "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/healthz').read())"

## A deployment of your own

1. Copy `deployments/example/` to `deployments/{environment}/`, where
   `{environment}` is your name for the host or the stage.
2. In its `.env`, set `CLIENT` to your organisation, `ENVIRONMENT` to
   the directory's name, and `SOLUTION` to the name the compose
   project, the edge network and the aliases take. Keep `SOLUTION` as
   `bugflow` unless two servers share a host.
3. Render the templates into `env/` with your values. Any Jinja
   renderer will do if it stops on a variable with no value: Ansible's
   `template` module does, and so does
   `deployments/scripts/render_env.py`, which reads a file of
   `name=value` lines.
4. Create the edge network: `docker network create bugflow-edge`.
5. Bring the composition up:

       docker compose -f deployments/{environment}/docker-compose.yml up -d --build

The tests under `deployments/tests/` read every composition under
`deployments/`, so a copy is held to the same rules as the example.

## The settings

A deployer supplies the variables that begin `bugflow_`, and the
secrets, which begin `vault_bugflow_`. A hosting platform supplies the
four that begin `project_`. A deployer with no such platform supplies
those too.

A variable with no default and no "not written" in its description is
required: a render without it fails and names it.

The Postgres password is written into a database address, so it must
hold only letters, digits, `-`, `.`, `_` and `~`.

### The database and the workflow engine

| Variable | Read by | Is |
|---|---|---|
| `bugflow_postgres_user` | `postgres`, `temporal`, and every program in its database address | The Postgres user |
| `vault_bugflow_postgres_password` | The same | That user's password. Postgres reads it only when it creates its data volume |
| `bugflow_database` | `postgres` and every program | The name of the database the programs keep their records in |
| `bugflow_temporal_namespace` | `worker`, `ingress` | The Temporal namespace. Default `default` |
| `bugflow_temporal_task_queue` | `worker`, `ingress` | The task queue the worker listens on. Default `bugflow` |
| `bugflow_temporal_ui_url` | `ingress` | The address people reach the workflow console at. Not written if empty |

### The forge

| Variable | Read by | Is |
|---|---|---|
| `bugflow_watched_repositories` | `worker`, `webhooks`, `poller` | The repositories this server watches, comma-separated: `owner/repo`, or `forgejo:owner/repo` for one on a Forgejo. Default none |
| `bugflow_ingress_url` | `webhooks` | The public address a forge posts deliveries to. `bugflow webhooks` does not run without it |
| `vault_bugflow_webhook_secret` | `ingress`, `webhooks`, `poller` | What a forge signs its deliveries with |
| `vault_bugflow_webhook_secret_previous` | `ingress` | The previous secret, supplied only while the secret is rotated. Not written if empty |
| `vault_bugflow_forge_token` | `worker`, `webhooks`, `poller` | The token pull requests are fetched and answered with: read pull requests and contents, write comments, labels and commit statuses, on the watched repositories alone. Registering webhooks also needs the right to administer a repository's hooks. Not written if empty |
| `bugflow_forgejo_url` | `worker`, `poller` | The address of a Forgejo whose pull requests are reviewed. Not written if empty |
| `vault_bugflow_forgejo_token` | `worker`, `poller` | A token for that Forgejo. Required if `bugflow_forgejo_url` is given |
| `bugflow_poll_interval_seconds` | `poller` | Seconds between polls. Default `60` |

### Models

| Variable | Read by | Is |
|---|---|---|
| `vault_bugflow_litellm_master_key` | `litellm`, `worker` | The key the proxy asks of a caller |
| `bugflow_small_model`, `bugflow_medium_model`, `bugflow_large_model` | `litellm` | The model that fills each role, as the proxy names models: a provider, a slash, and the provider's name for the model. Default empty, and the proxy does not publish a role with no model |
| `vault_bugflow_small_api_key`, `vault_bugflow_medium_api_key`, `vault_bugflow_large_api_key` | `litellm` | The key each role's model is called with. Default empty |
| `bugflow_model_class_small`, `bugflow_model_class_medium`, `bugflow_model_class_large` | `worker` | What each class of model asks the proxy for. Default the role of the class's own name |
| `bugflow_judge_model` | `worker` | One model for every class, overriding all of them. Not written if empty |
| `bugflow_judge_requests_per_second` | `worker` | Requests a second each judging queue allows, across every worker on it. Default `0.2` |
| `bugflow_judge_requests_per_second_small`, `bugflow_judge_requests_per_second_medium`, `bugflow_judge_requests_per_second_large` | `worker` | The same for one class of model. `0` is no limit. Not written if empty |
| `bugflow_tokenomic_s3_bucket` | `worker` | The bucket the content of every call to a model is kept in. Not written if empty, and then the next four are not read |
| `bugflow_tokenomic_s3_endpoint` | `worker` | That bucket's S3 endpoint |
| `bugflow_tokenomic_s3_region` | `worker` | Its region. Default `us-east-1` |
| `vault_bugflow_tokenomic_s3_access_key`, `vault_bugflow_tokenomic_s3_secret_key` | `worker` | A key that reads and writes that bucket alone |

Once a policy deployment is in force that holds a policy for a model
to judge, the worker checks the proxy as it starts and does not start
until the proxy publishes all three roles. So each role needs a model
before the first deployment, even if two roles share one.

### Reviewing

| Variable | Read by | Is |
|---|---|---|
| `bugflow_periods_timezone` | `worker` | The time zone a calendar period starts and ends in, as an IANA name. Default `UTC` |
| `bugflow_review_agents` | `worker` | The reviewers this worker runs, by id, comma-separated. Not written if empty, and then every reviewer the deployment in force holds is run |
| `bugflow_policy_checks` | `worker`, `ingress`, `api`, `migrate` | The checks this server performs, comma-separated. Not written if not defined, and then they are the ones the package has. Defined and empty, a manifest naming a check is refused |
| `bugflow_review_runner` | `worker` | The runner reviews are dispatched to. The package has one, `managed`. Not written if empty, and then the next five are not read and nothing is dispatched |
| `bugflow_review_agent_model` | `worker` | The model a managed agent's sessions run, by its platform's name for it |
| `vault_bugflow_review_runner_api_key` | `worker` | The key sessions are started with. A key of its own, so that a spend limit on it does not cap the proxy |
| `vault_bugflow_review_repository_token` | `worker` | A token that can only read the watched repositories, which a session mounts them with. Never the forge token |
| `bugflow_review_completion_webhook` | `worker` | Any value says the runner's platform tells the ingress when a session stops. Not written if empty |
| `bugflow_forge_clone_url` | `worker` | The address a session clones repositories from. Not written if empty |
| `vault_bugflow_review_webhook_secret` | `ingress` | What the runner's platform signs its completion webhook with. Not written if empty, and then that route accepts nothing |

### The API

| Variable | Read by | Is |
|---|---|---|
| `bugflow_roles_claim` | `api` | The claim of a token that lists a caller's roles |
| `bugflow_policy_deployer_role` | `api` | The role that may deploy policies |
| `project_oidc_issuer` | `api` | The identity provider's address. Default empty |
| `project_oidc_audience` | `api` | The audience a token must be addressed to. Default empty |
| `project_oidc_clients` | `api` | The clients registered at the provider, by name. The API accepts tokens issued to the one named `policies-pipeline`, by its `client_id`. Not written until that client exists |
| `project_build_sha` | `worker`, `ingress`, `api`, `migrate` | The full git sha of the commit the image was built from, recorded with every journal entry. Not written if not defined |

The API does not start until its settings hold an issuer, an audience,
a client, a roles claim and a deployer role. Compose starts it again
until they do, so a first render made before the provider has
registered the client needs only a second render and `up`.

## The order

`migrate` runs first and exits. The worker, the ingress and the API
start only after it has finished without error, and none of them
changes the database's tables. Bringing a newer build up is the same
command as the first: Compose runs `migrate` again before it replaces
the programs.

## How policies reach a server

A server reviews under a policy deployment: the reviewers, policies
and doctrine of one commit of a policy repository. It holds none until
it is sent one.

A policy repository's pipeline sends one through the API:

    bugflow deploy-policies DIRECTORY --repository OWNER/NAME \
        --commit SHA --api URL

The pipeline signs in to the identity provider as a client with no
person behind it, with the four settings `bugflow deploy-policies
--help` names, and that client must hold the deployer role. With
`--check` the server parses the files and stores nothing, which is
what a pipeline runs on a pull request.

On the host, for a server no pipeline reaches yet:

    docker compose -f deployments/{environment}/docker-compose.yml \
        run --rm -v /path/to/policies:/policies:ro migrate \
        bugflow install-policies /policies \
        --repository OWNER/NAME --commit SHA

Either way the deployment is stored and put in force. The worker and
the ingress see that within a few seconds and stop, Compose starts
them again, and they read the new deployment as they start.

## A server with nothing installed

A server that was never sent a deployment starts all the same. The
ingress receives deliveries and hands them to Temporal. The worker says
`reviews nothing: no policy deployment is in force`, registers no
review workflow, and waits. Nothing is published to a pull request.
The first deployment put in force stops both, and they start again
reviewing under it.

## How webhooks are registered

For repositories on github.com, run on the host:

    docker compose -f deployments/{environment}/docker-compose.yml \
        --profile webhooks run --rm webhooks

It registers a webhook on each repository `bugflow_watched_repositories`
names, pointing at `/webhooks/github` under `bugflow_ingress_url` and
signed with the webhook secret. It changes nothing where the forge
already agrees, so it can be run on every deploy.

For a repository on a Forgejo, add the webhook by hand in the
repository's settings: the address is `/webhooks/forgejo` under the
ingress's public address, and the secret is the same one.

Where a forge cannot reach the ingress, as on a laptop, the poller
stands in for the webhooks:

    docker compose -f deployments/{environment}/docker-compose.yml \
        --profile polling up -d poller

## What the composition leaves to the host

- **TLS and routing.** No service publishes a port. The host runs a
  proxy, joins it to the edge network, `{SOLUTION}-edge`, and routes a
  host name to each alias on port 8000: `{SOLUTION}-ingress` and
  `{SOLUTION}-api`. The proxy holds the certificates.
- **A login in front of the workflow console.** `{SOLUTION}-temporal-ui`
  listens on port 8080 and authenticates nobody. Route to it only
  behind a login, or not at all.
- **The edge network.** It is external to the composition, so the host
  creates it before the first `up`.
- **An identity provider for the API.** The API checks every caller's
  token itself, against the provider's published keys, so the proxy
  routes to it with no login in front. The provider needs a client for
  the policy pipeline, of the kind that signs in with no person behind
  it, holding the deployer role, with access tokens that are JWTs and
  carry the roles claim.
- **Backups.** Everything the server keeps is in the `pgdata` volume,
  unless a bucket is named for the content of model calls.
