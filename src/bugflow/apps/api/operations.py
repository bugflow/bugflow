"""The routes and the pages that show what the server spent and did.

``GET /api/operations/runs/{run_id}?workflow_id=...`` reads one run:
each costed fact it recorded, each allowance that covers it beside what
the allowance measures, and every entry it recorded. It needs the role
``SETTINGS_ROLE`` names, as the settings do: whoever may change what a
gnome does may see what it spent.

``GET /api/operations/repositories/{forge}/{owner}/{name}`` reads one
repository: what each gnome is set to do there, each allowance that
covers it over its current period, what it spent by layer and agent
over ``since`` to ``until``, by default the thirty days to now, and the
runs that spent it. ``layer`` and ``agent_id`` list only the runs of
that spend row, where an empty value names the facts that name none.

``GET /api/operations/layers`` and ``GET /api/operations/agents`` read
what was spent over the same period by every pace layer or every agent,
by repository. ``layer`` or ``agent_id`` reads one, with the runs its
figures are made of. Each lists the allowances that name a layer or an
agent, or the one read.

``GET /api/operations/allowances`` reads what one scope is allowed,
named by ``forge``, ``repo`` or ``owner``, ``layer`` and ``agent_id``,
each of which may be left out to mean any: the allowances it declares,
those it inherits from each wider scope that covers it, and the ceiling
each run in it is handed, with the allowance each limit comes from.
``PUT`` with a scope, a cadence and both limits declares the scope's
allowance for that cadence, where a limit of null is no limit, and
``DELETE`` with ``per`` revokes it. Each answers with what the scope is
then allowed, and journals the change with the caller as who made it.

``GET /operations/run``, ``/operations/repository``,
``/operations/layers``, ``/operations/layer``, ``/operations/agents``,
``/operations/agent`` and ``/operations/allowances`` are the pages that
show them. Each signs a
person in through the settings page's client, and holds no data until
a route gives it some, so it needs no token.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.errors import RunNotFoundError
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.dtos.declare_allowance import DeclareAllowanceRequest
from bugflow.review.dtos.read_allowances import ReadAllowancesRequest
from bugflow.review.dtos.read_repository_operations import (
    ReadRepositoryOperationsRequest,
)
from bugflow.review.dtos.read_run_operations import (
    AllowanceCheck,
    ReadRunOperationsRequest,
)
from bugflow.review.dtos.read_spend_operations import (
    Dimension,
    ReadSpendOperationsRequest,
)
from bugflow.review.usecases.declare_allowance import (
    DeclareAllowanceUseCase,
)
from bugflow.review.usecases.read_allowances import ReadAllowancesUseCase
from bugflow.review.usecases.read_repository_operations import (
    ReadRepositoryOperationsUseCase,
)
from bugflow.review.usecases.read_run_operations import (
    ReadRunOperationsUseCase,
)
from bugflow.review.usecases.read_spend_operations import (
    ReadSpendOperationsUseCase,
)
from bugflow.shared.domain.values.budget import Budget
from bugflow.shared.domain.values.caller import Caller

#: The pages, kept beside this module.
RUN_PAGE = "operations_run_page.html"
REPOSITORY_PAGE = "operations_repository_page.html"
ALLOWANCES_PAGE = "operations_allowances_page.html"
#: The pages of every layer or agent and of one, each served for both:
#: ``__BY__`` and ``__EVERY__`` in them name which.
SPEND_LIST_PAGE = "operations_spend_list_page.html"
SPEND_PAGE = "operations_spend_page.html"
#: Each dimension's name, and its name for every one of it.
DIMENSIONS: dict[Dimension, str] = {"layer": "layers", "agent": "agents"}
#: What every page shares: its script and its style.
PAGES_SCRIPT = "operations_pages.js"
PAGES_STYLE = "operations_pages.css"
#: The period a repository's spend is read over when none is named.
DEFAULT_PERIOD = timedelta(days=30)


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class OperationsReading:
    """What the operations routes are served with."""

    #: The role a caller needs to read them.
    role: str
    run: Callable[[], ReadRunOperationsUseCase]
    repository: Callable[[], ReadRepositoryOperationsUseCase]
    spend: Callable[[], ReadSpendOperationsUseCase]
    allowances: Callable[[], ReadAllowancesUseCase]
    #: Each call declares through a use case of its own, a run of its
    #: own in the journal.
    declare: Callable[[], DeclareAllowanceUseCase]
    #: The cadences an allowance may be counted per, as the method
    #: names them.
    cadences: tuple[str, ...]
    clock: Clock


class Scope(BaseModel):
    model_config = ConfigDict(frozen=True)

    forge: str
    owner: str
    repo: str
    layer: str
    agent_id: str


class Allowance(BaseModel):
    """One allowance beside what it measures. The figures are None where
    it sets no money limit or where its period cannot be found, which
    ``unmeasured`` then says."""

    model_config = ConfigDict(frozen=True)

    scope: Scope
    per: str
    allowed_usd: float | None
    allowed_turns: float | None = None
    spent_usd: float | None = None
    left_usd: float | None = None
    over_usd: float | None = None
    has_room: bool | None = None
    #: The period measured: a calendar period, or the run itself for an
    #: allowance per run.
    since: datetime | None = None
    until: datetime | None = None
    facts: int | None = None
    unmeasured: str = ""


class Cost(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    occurred_at: datetime
    kind: str
    layer: str
    agent_id: str
    usd: float


class Activity(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: str
    occurred_at: datetime
    event_type: str
    agent_id: str
    pr_number: int | None


class RunOperations(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str
    run_id: str
    forge: str
    repo: str
    spent_usd: float
    costs: list[Cost]
    allowances: list[Allowance]
    activity: list[Activity]


class Setting(BaseModel):
    model_config = ConfigDict(frozen=True)

    gnome: str
    behaviour: str
    profile: str
    set_by: str
    set_at: datetime | None


class SpendRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    layer: str
    agent_id: str
    usd: float
    facts: int
    runs: int


class RunRow(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: str
    run_id: str
    forge: str
    repo: str
    first: datetime
    last: datetime
    usd: float
    facts: int


class RepositoryOperations(BaseModel):
    model_config = ConfigDict(frozen=True)

    forge: str
    repo: str
    since: datetime
    until: datetime
    spent_usd: float
    settings: list[Setting]
    allowances: list[Allowance]
    spend: list[SpendRow]
    #: The spend row the runs are listed for, or None for every run.
    layer: str | None
    agent_id: str | None
    runs: list[RunRow]


class SpendCell(BaseModel):
    model_config = ConfigDict(frozen=True)

    forge: str
    repo: str
    layer: str
    agent_id: str
    usd: float
    facts: int
    runs: int


class SpendOperations(BaseModel):
    model_config = ConfigDict(frozen=True)

    by: str
    #: The layer or agent read, or None for every one.
    name: str | None
    since: datetime
    until: datetime
    spent_usd: float
    cells: list[SpendCell]
    allowances: list[Allowance]
    #: The runs the cells are made of, where one layer or agent is read.
    runs: list[RunRow]


class AppliedAllowance(Allowance):
    #: Declared on the scope read, and changed there; otherwise
    #: inherited from the wider scope it names.
    own: bool


class Source(BaseModel):
    """The allowance a limit comes from."""

    model_config = ConfigDict(frozen=True)

    scope: Scope
    per: str


class Ceiling(BaseModel):
    model_config = ConfigDict(frozen=True)

    usd: float | None
    usd_from: Source | None
    turns: float | None
    turns_from: Source | None


class Allowances(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: Scope
    #: The cadences an allowance may be declared per.
    cadences: list[str]
    applied: list[AppliedAllowance]
    #: What each run in the scope is handed, or None for nothing.
    ceiling: Ceiling | None


class Declaration(BaseModel):
    """A scope's allowance for one cadence, as a person sets it: both
    limits, where null is no limit."""

    model_config = ConfigDict(frozen=True)

    scope: Scope
    per: str
    usd: float | None
    turns: float | None


def _source(binding: SpendBinding | None) -> Source | None:
    if binding is None:
        return None
    return Source(scope=_scope(binding.scope), per=binding.per)


def _page(name: str) -> str:
    """One of the files the pages are made of, kept beside this module."""
    return files("bugflow.apps.api").joinpath(name).read_text()


def _period(
    since: datetime | None, until: datetime | None, now: datetime
) -> tuple[datetime, datetime]:
    """The period a route names, by default the thirty days to now."""
    ends = _aware(until) or now
    return _aware(since) or ends - DEFAULT_PERIOD, ends


def _aware(at: datetime | None) -> datetime | None:
    """A moment named with no timezone, taken as UTC."""
    if at is None or at.tzinfo is not None:
        return at
    return at.replace(tzinfo=UTC)


def _scope(scope: SpendScope) -> Scope:
    return Scope(
        forge=scope.forge,
        owner=scope.owner,
        repo=scope.repo,
        layer=scope.layer,
        agent_id=scope.agent_id,
    )


def _allowance(check: AllowanceCheck) -> Allowance:
    held = check.remaining
    return Allowance(
        scope=_scope(check.binding.scope),
        per=check.binding.per,
        allowed_usd=check.binding.budget.usd,
        allowed_turns=check.binding.budget.turns,
        spent_usd=None if held is None else held.spent.usd,
        left_usd=None if held is None else held.left_usd,
        over_usd=None if held is None else held.over_usd,
        has_room=None if held is None else held.has_room,
        since=None if held is None else held.since,
        until=None if held is None else held.until,
        facts=None if held is None else held.spent.facts,
        unmeasured=check.unmeasured,
    )


def _spend_pages(app: FastAPI, by: str, every: str) -> None:
    """Serve the pages of every layer or agent and of one."""

    def made(name: str) -> str:
        return _page(name).replace("__BY__", by).replace("__EVERY__", every)

    @app.get(f"/operations/{every}", response_class=HTMLResponse)
    def list_page() -> str:
        return made(SPEND_LIST_PAGE)

    @app.get(f"/operations/{by}", response_class=HTMLResponse)
    def one_page() -> str:
        return made(SPEND_PAGE)


def operations_routes(
    app: FastAPI,
    caller: Callable[..., Caller],
    reading: OperationsReading,
) -> None:
    """Add the operations routes and pages to ``app``."""

    def operator(who: Annotated[Caller, Depends(caller)]) -> Caller:
        if reading.role not in who.roles:
            raise HTTPException(403, "this caller may not read operations")
        return who

    @app.get("/api/operations/runs/{run_id}")
    def read_run(
        run_id: str,
        workflow_id: str,
        who: Annotated[Caller, Depends(operator)],
    ) -> RunOperations:
        try:
            read = reading.run().execute(
                ReadRunOperationsRequest(
                    workflow_id=workflow_id,
                    run_id=run_id,
                    now=reading.clock.now(),
                )
            )
        except RunNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        return RunOperations(
            workflow_id=read.workflow_id,
            run_id=read.run_id,
            forge=read.forge,
            repo=read.repo,
            spent_usd=read.spent_usd,
            costs=[
                Cost(
                    event_id=one.event_id,
                    occurred_at=one.occurred_at,
                    kind=one.kind,
                    layer=one.layer,
                    agent_id=one.agent_id,
                    usd=one.usd,
                )
                for one in read.costs
            ],
            allowances=[_allowance(one) for one in read.allowances],
            activity=[
                Activity(
                    event_id=one.event_id,
                    occurred_at=one.occurred_at,
                    event_type=one.event_type,
                    agent_id=one.agent_id,
                    pr_number=one.pr_number,
                )
                for one in read.activity
            ],
        )

    @app.get("/api/operations/repositories/{forge}/{owner}/{name}")
    def read_repository(
        forge: str,
        owner: str,
        name: str,
        who: Annotated[Caller, Depends(operator)],
        since: datetime | None = None,
        until: datetime | None = None,
        layer: str | None = None,
        agent_id: str | None = None,
    ) -> RepositoryOperations:
        now = reading.clock.now()
        since, until = _period(since, until, now)
        try:
            asked = ReadRepositoryOperationsRequest(
                forge=forge,
                repo=f"{owner}/{name}",
                since=since,
                until=until,
                now=now,
                layer=layer,
                agent_id=agent_id,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        read = reading.repository().execute(asked)
        return RepositoryOperations(
            forge=read.forge,
            repo=read.repo,
            since=read.since,
            until=read.until,
            spent_usd=read.spent_usd,
            settings=[
                Setting(
                    gnome=one.gnome,
                    behaviour=one.behaviour,
                    profile=one.profile,
                    set_by=one.set_by,
                    set_at=one.set_at,
                )
                for one in read.settings
            ],
            allowances=[_allowance(one) for one in read.allowances],
            spend=[SpendRow(**one.model_dump()) for one in read.spend],
            layer=read.layer,
            agent_id=read.agent_id,
            runs=[RunRow(**one.model_dump()) for one in read.runs],
        )

    def read_spend(
        by: Dimension,
        name: str | None,
        since: datetime | None,
        until: datetime | None,
    ) -> SpendOperations:
        now = reading.clock.now()
        begins, ends = _period(since, until, now)
        try:
            asked = ReadSpendOperationsRequest(
                by=by, name=name, since=begins, until=ends, now=now
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        read = reading.spend().execute(asked)
        return SpendOperations(
            by=read.by,
            name=read.name,
            since=read.since,
            until=read.until,
            spent_usd=read.spent_usd,
            cells=[SpendCell(**one.model_dump()) for one in read.cells],
            allowances=[_allowance(one) for one in read.allowances],
            runs=[RunRow(**one.model_dump()) for one in read.runs],
        )

    @app.get("/api/operations/layers")
    def read_layers(
        who: Annotated[Caller, Depends(operator)],
        since: datetime | None = None,
        until: datetime | None = None,
        layer: str | None = None,
    ) -> SpendOperations:
        return read_spend("layer", layer, since, until)

    @app.get("/api/operations/agents")
    def read_agents(
        who: Annotated[Caller, Depends(operator)],
        since: datetime | None = None,
        until: datetime | None = None,
        agent_id: str | None = None,
    ) -> SpendOperations:
        return read_spend("agent", agent_id, since, until)

    def scope_of(
        forge: str, repo: str, owner: str, layer: str, agent_id: str
    ) -> SpendScope:
        if (repo or owner) and not forge:
            raise HTTPException(
                422,
                "a scope that names a repository or an owner names its forge",
            )
        try:
            return SpendScope(
                forge=forge,
                repo=repo,
                owner=owner,
                layer=layer,
                agent_id=agent_id,
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    def allowed(scope: SpendScope) -> Allowances:
        read = reading.allowances().execute(
            ReadAllowancesRequest(scope=scope, now=reading.clock.now())
        )
        ceiling = read.ceiling
        return Allowances(
            scope=_scope(read.scope),
            cadences=list(reading.cadences),
            applied=[
                AppliedAllowance(
                    **_allowance(one.check).model_dump(), own=one.own
                )
                for one in read.applied
            ],
            ceiling=None
            if ceiling is None
            else Ceiling(
                usd=ceiling.usd,
                usd_from=_source(ceiling.usd_from),
                turns=ceiling.turns,
                turns_from=_source(ceiling.turns_from),
            ),
        )

    def declared(
        scope: SpendScope, per: str, budget: Budget | None, who: Caller
    ) -> Allowances:
        if per not in reading.cadences:
            raise HTTPException(
                422,
                f"{per!r} is not a cadence; an allowance is per one of "
                f"{', '.join(reading.cadences)}",
            )
        reading.declare().execute(
            DeclareAllowanceRequest(
                scope=scope, per=per, budget=budget, declared_by=who.subject
            )
        )
        return allowed(scope)

    @app.get("/api/operations/allowances")
    def read_allowances(
        who: Annotated[Caller, Depends(operator)],
        forge: str = "",
        repo: str = "",
        owner: str = "",
        layer: str = "",
        agent_id: str = "",
    ) -> Allowances:
        return allowed(scope_of(forge, repo, owner, layer, agent_id))

    @app.put("/api/operations/allowances")
    def declare_allowance(
        body: Declaration, who: Annotated[Caller, Depends(operator)]
    ) -> Allowances:
        limits = (body.usd, body.turns)
        if any(one is not None and one < 0 for one in limits):
            raise HTTPException(422, "a limit is not below zero")
        scope = body.scope
        return declared(
            scope_of(
                scope.forge,
                scope.repo,
                scope.owner,
                scope.layer,
                scope.agent_id,
            ),
            body.per,
            Budget(usd=body.usd, turns=body.turns),
            who,
        )

    @app.delete("/api/operations/allowances")
    def revoke_allowance(
        per: str,
        who: Annotated[Caller, Depends(operator)],
        forge: str = "",
        repo: str = "",
        owner: str = "",
        layer: str = "",
        agent_id: str = "",
    ) -> Allowances:
        return declared(
            scope_of(forge, repo, owner, layer, agent_id), per, None, who
        )

    @app.get("/operations/allowances", response_class=HTMLResponse)
    def allowances_page() -> str:
        return _page(ALLOWANCES_PAGE)

    for by, every in DIMENSIONS.items():
        _spend_pages(app, by, every)

    @app.get("/operations/pages.js")
    def pages_script() -> Response:
        return Response(_page(PAGES_SCRIPT), media_type="text/javascript")

    @app.get("/operations/pages.css")
    def pages_style() -> Response:
        return Response(_page(PAGES_STYLE), media_type="text/css")

    @app.get("/operations/run", response_class=HTMLResponse)
    def run_page() -> str:
        return _page(RUN_PAGE)

    @app.get("/operations/repository", response_class=HTMLResponse)
    def repository_page() -> str:
        return _page(REPOSITORY_PAGE)
