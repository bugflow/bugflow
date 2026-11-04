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

``GET /operations/run``, ``/operations/repository``,
``/operations/layers``, ``/operations/layer``, ``/operations/agents``
and ``/operations/agent`` are the pages that show them. Each signs a
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
from bugflow.review.usecases.read_repository_operations import (
    ReadRepositoryOperationsUseCase,
)
from bugflow.review.usecases.read_run_operations import (
    ReadRunOperationsUseCase,
)
from bugflow.review.usecases.read_spend_operations import (
    ReadSpendOperationsUseCase,
)
from bugflow.shared.domain.values.caller import Caller

#: The pages, kept beside this module.
RUN_PAGE = "operations_run_page.html"
REPOSITORY_PAGE = "operations_repository_page.html"
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


def _allowance(check: AllowanceCheck) -> Allowance:
    scope = check.binding.scope
    held = check.remaining
    return Allowance(
        scope=Scope(
            forge=scope.forge,
            owner=scope.owner,
            repo=scope.repo,
            layer=scope.layer,
            agent_id=scope.agent_id,
        ),
        per=check.binding.per,
        allowed_usd=check.binding.budget.usd,
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
