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
[docs/architecture.md](docs/architecture.md) explains what is deployed
where and what each part depends on.
[docs/gnomes.md](docs/gnomes.md) explains the rules a server reviews
by, for a person who maintains them.
[bugflow/bugflow-examples](https://github.com/bugflow/bugflow-examples)
holds policies a server can review with, each example laid out as a
policy repository.
[docs/review.md](docs/review.md) says what a review writes on a pull
request and where each part comes from, for an author and for whoever
keeps a binding.
[docs/words.md](docs/words.md) lists what bugflow calls things and
where each word is defined.
[docs/repository-origins.md](docs/repository-origins.md) describes the
inventory and explicit migration of retained repository references.

