# Bugflow

Bugflow is self-hosted infrastructure for teams that want to converge on
methodology for using AI to augment human creativity.

It implements:

- a [clankos.org](https://www.clankos.org) archive service;
- MCP-based distributed workflow orchestration for human/AI dyads;
- tooling to accelerate developer productivity.

## Running a server

`deployments/example/` is a composition that brings up one server: the
programs of this repository, Postgres, Temporal and a model proxy. For
a local run:

    make env
    make up

[docs/deploying.md](docs/deploying.md) describes the settings, how to
copy the composition for a host of your own, and how policies reach a
server.
