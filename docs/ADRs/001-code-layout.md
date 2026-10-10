# ADR 001: Code layout

## Status

Proposed, 2026-10-09.

## Decision

The repository has three directories: `docs/`, `src/` and
`deployments/`. Others are added when they are needed, by amending this
record.

A Python module's path is:

    src/bugflow/{context}/{layer}/{kind or area}/{module}.py

### Contexts

A context is one part of what Bugflow does, named for that part:
`archive`, `review`. It is the first directory under `src/bugflow/`.

Two names beside the contexts are not contexts:

- `shared/` holds what more than one context uses.
- `apps/` holds one directory for each program that is run: a server, a
  worker, a command. An application wires contexts to the technology
  that runs them.

`apps/shared/` holds code that several programs compose and that
crosses contexts: stamping the journal with the build, the reviewers
in force, deploying policies with the declarations they carry. It is
not a program and not a context. A program may import it; no context
may, as no context imports an application; and it imports no program.

### Layers

A context has up to four layers:

| Layer | Holds |
|---|---|
| `domain/` | What the context is about, and the interfaces it needs from outside |
| `dtos/` | The messages its use cases accept and answer with |
| `usecases/` | What it can be asked to do |
| `infrastructure/` | Implementations of the domain's interfaces: a database, a store, another service |

`shared/` has `domain/` and `infrastructure/`.

### Inside `domain/`

A domain is divided by kind, by area, or both.

A kind is what sort of class a module holds:

| Kind | Holds |
|---|---|
| `models` | Entities, which have an identity |
| `values` | Values, which have none |
| `repositories` | Interfaces that keep one kind of entity |
| `services` | Interfaces to anything else outside |
| `errors` | The exceptions the domain raises |

An area is a part of the context's business, such as `billing`. Any
directory under `domain/` that is not named for a kind is an area, and
an area may hold kinds:

    domain/                domain/
    ├── models/            └── billing/
    ├── repositories/          ├── invoice.py
    └── errors.py              ├── repositories/
                               └── errors.py

A kind may be a module or a directory. A module in a domain or an area
that is not named for a kind holds entities. A small domain needs no
directories.

### Tests

A context's tests are in `{context}/tests/`, and an application's in
`apps/{application}/tests/`.

### Documents

Decision records are `docs/ADRs/NNN-title.md`.

### Deployments

A third directory, `deployments/`, holds what brings the programs up
on a host. `deployments/{environment}/docker-compose.yml` is one
environment's composition, and the `.env` beside it names the client,
the solution and the environment. `deployments/env/*.env.j2` are the
templates of the programs' settings, which a deployer renders into
`env/`. `deployments/scripts/` holds what the compositions mount and
what prepares a local run. `deployments/tests/` holds the tests that
read those files. `Dockerfile` and `litellm/`, at the root of the
repository, are built and mounted by the compositions.
`deployments/example/` is the composition this repository is tested
against. It names no organisation, and a deployer copies it. Nothing
under `src/` reads anything under `deployments/`.

## Rules

1. Inside a context, imports point inward: `infrastructure/` and
   `usecases/` may import `dtos/` and `domain/`; `dtos/` may import
   `domain/`; `domain/` imports none of them.
2. A context imports no other context. Any context may import `shared/`.
3. An application may import any context. Nothing imports an
   application.
4. A use case does not import what runs it: no web framework, no
   workflow engine, no database driver.

## Consequences

A context's code and its tests are in one directory.

A context declares what it needs from outside as an interface in its
`domain/`. An application supplies the implementation. A use case
therefore runs unchanged in a test, a web request or a workflow.
