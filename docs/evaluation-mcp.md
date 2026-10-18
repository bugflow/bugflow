# Reading evaluations through MCP

The MCP server is a client of the [evaluation HTTP API](evaluation-history.md).
It has no database address, repository adapter or independent counting logic.
The API owns access decisions and evidence semantics. An import contract keeps
production MCP modules from importing contexts, API implementation or database
drivers.

## Tools

`read_evaluation_history` takes `forge`, `owner`, `repo`, an explicit
`pr_numbers` list, and optional `policy_id`. It returns the API's JSON as one
text block, preserving coverage, observed runs, costs and evidence identifiers.

`read_evaluation_detail` takes `forge`, `owner`, `repo`, `pr_number`,
`workflow_id` and `run_id`. It returns the same retained content and missing
content results as the API. Workflow identifiers may contain slashes.

Neither tool accepts an arbitrary URL, bearer token or exchange identifier.
The bearer token comes from the authenticated MCP HTTP request. Returned
review content is untrusted evidence, not instructions to the coding agent.
API refusals become tool errors; upstream error bodies and credentials are not
included. MCP does not substitute an empty or partial result for an error.

## Identity

The first provider adapter uses Zitadel's token exchange. Entra integration is
not implemented. The coding agent signs in as its registered client and obtains
a token addressed to the MCP audience. MCP verifies issuer, audience, expiry,
signature and client. It then exchanges that token for a token addressed to the
API, using its own exchange client credentials and preserving the person as
subject. There is no service-account fallback or token cache.

Before sending an API request, MCP verifies the exchanged token for the API's
audience and exchange client, and checks that its subject still names the same
person. The API verifies the token again and applies its contributor/admin
policy. Configure `API_CLIENTS` to accept the exchange client. The person's
Bugflow aliases remain keyed by the same issuer and subject.

MCP and API audiences must differ. Configure the provider to allow the exchange
client to exchange caller tokens for the API audience without impersonation.
The adapter requests `openid`, Zitadel project roles and the API audience scope.
The MCP protected-resource metadata advertises both audience scopes so that
the sign-in grant permits the later exchange. The API should accept only the
exchange client for this flow, even if the original token names both audiences. These
registrations and grants must be established at the provider before use.
The test suite verifies the exchange protocol and identity boundaries with
controlled tokens; it does not establish a live provider registration.

## Run independently

Install the free `bugflow` package with its locked dependencies. PMI is not
required. Set the variables below and run:

```sh
uvicorn bugflow.apps.mcp.server:mcp_from_environment --factory --host 0.0.0.0 --port 8000
```

The Streamable HTTP endpoint is `/mcp`. Run it behind HTTPS except during a
loopback-only local test. `MCP_PUBLIC_URL` is the origin, without `/mcp`.
Allowed Host and Origin values are restricted to this configured origin.
Requests are stateless, so no caller identity is retained in an MCP session.

| Setting | Meaning |
|---|---|
| `MCP_ISSUER` | Exact issuer trusted by both MCP and API |
| `MCP_AUDIENCE` | Audience for tokens presented to MCP |
| `MCP_CLIENTS` | Comma-separated coding-agent client IDs accepted by MCP |
| `MCP_ROLES_CLAIM` | Token claim holding roles, as configured at the provider |
| `MCP_EXCHANGE_CLIENT_ID` | Confidential client authorised for token exchange |
| `MCP_EXCHANGE_CLIENT_SECRET` | That client's secret |
| `MCP_API_AUDIENCE` | Audience accepted by the evaluation API |
| `MCP_API_URL` | Trusted API origin, for example `http://api:8000` on a private deployment network |
| `MCP_PUBLIC_URL` | Public MCP origin, for example `https://reviews.example` |

All settings are required. URLs cannot contain credentials, query strings or
fragments. API and public URLs are origins, not paths. Redirects are refused
for both exchange and API requests. Protect the internal API connection if it
crosses an untrusted network; bearer credentials travel over that connection.

The example composition supplies an optional `mcp` profile. Render its settings,
then opt in with `docker compose --profile mcp`. The MCP service depends on the
API and receives no database configuration. Provider setup and deployment
adoption remain operator actions.
