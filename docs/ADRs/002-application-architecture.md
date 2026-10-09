# ADR 002: Application architecture

## Status

Proposed, 2026-10-09.

## Decision

ADR 001 says where a module goes. This record says what each part
does, what it is given, and what it does not know.

### The parts

| Part | Is | Knows |
|---|---|---|
| Domain | Entities, values, and the interfaces the context needs from outside | Nothing but itself |
| Use case | One thing the context can be asked to do | Its domain and its messages |
| Infrastructure adapter | One implementation of one interface, over one technology | The interface it implements, and its technology |
| Application | A program that is run | Everything it assembles |

### Interfaces

An interface is a `typing.Protocol` in a domain: the methods a use
case will call, and nothing about how they are answered.

    class BindingRepository(Protocol):
        def for_ledger(self, ledger_id: str) -> Binding | None: ...

An adapter implements an interface by having those methods. It does
not inherit from the protocol.

### Use cases

A use case is a class with one method, `execute`, which takes a
request and answers with a response, both from `dtos/`. It is given
everything it needs from outside when it is constructed, each thing
typed as an interface.

    class ReadFileUseCase:
        def __init__(
            self, bindings: BindingRepository, blocks: BlockStoreService
        ) -> None:
            self._bindings = bindings
            self._blocks = blocks

        def execute(self, request: ReadFileRequest) -> ReadFileResponse:
            ...

A use case uses what it was given and does not know what it was
given: a database or a dictionary, a real store or a test's. It does
not know what runs it either: a web request, a command, a workflow.

Everything the software does is in a use case or in the domain a use
case calls.

### Infrastructure adapters

An adapter implements one interface over one technology:
`SqlBindingRepository` over a database, `InMemoryBindingRepository`
over a dictionary. Both are in `infrastructure/`, and a use case
cannot tell them apart.

### Applications

An application is a composition root. It is the one place where the
parts are put together, and it is driven by configuration. When it
starts, it:

1. reads its configuration from the environment;
2. constructs the adapters the configuration calls for;
3. constructs each use case, passing it its adapters;
4. connects each use case to what runs it.

    def host_from_environment(environ: Mapping[str, str]) -> FastAPI:
        bindings = SqlBindingRepository(environ["DATABASE_URL"])
        blocks = S3BlockStore(environ["S3_BUCKET"])
        return create_host(read=ReadFileUseCase(bindings, blocks))

What an application adds of its own is translation: it turns what
arrives into a request, calls `execute`, and turns the response into
what leaves. It decides nothing else.

### What runs a use case

| Application | A use case is run by |
|---|---|
| A server | A route, for each request it takes |
| A command | A subcommand, once |
| A worker | A workflow, or an activity of one |

A workflow is application code, like a route: a shell around one use
case. The worker application decides how the workflow engine runs
it, either the whole use case in one activity, or the use case in the
workflow with an activity answering each interface it calls. The use
case is the same class in each.

### Between contexts

A context that needs something from another declares an interface for
it in its own domain. An application supplies an adapter that
implements the interface by calling the other context's use case.
That adapter is in the application, which is the only code that
imports both contexts.

### Tests

| What | Is tested |
|---|---|
| A use case | Constructed with in-memory adapters; no framework, database or network |
| An adapter | Against its technology |
| An application | Through its own entrance: a request, a command line, a workflow run |

## Rules

1. A use case receives every dependency through its constructor,
   typed as an interface of a domain.
2. A use case constructs no adapter, reads no configuration and
   imports no application.
3. Only an application reads configuration, and only an application
   constructs adapters and use cases.
4. An application holds no rule of the business. A route, a
   subcommand, a workflow and an activity translate and call.
5. An adapter that calls another context's use case is in an
   application.

## Consequences

A use case runs unchanged in a test, a web request, a command and a
workflow, because none of them is in it.

Changing a technology is a new adapter and a change to the
applications that construct it. No use case changes.

A reader following one request passes through four places: the
application, the use case, the interface and the adapter. A small
feature adds a module to each.
