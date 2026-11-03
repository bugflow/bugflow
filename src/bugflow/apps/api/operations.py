"""The routes and the pages that show what the server spent and did.

``GET /api/operations/runs/{run_id}?workflow_id=...`` reads one run:
each costed fact it recorded, each allowance that covers it beside what
the allowance measures, and every entry it recorded. It needs the role
``SETTINGS_ROLE`` names, as the settings do: whoever may change what a
gnome does may see what it spent.

``GET /operations/run`` is the page that shows one run. It signs a
person in through the settings page's client, and holds no data until
the route gives it some, so it needs no token.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from importlib.resources import files
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.errors import RunNotFoundError
from bugflow.review.dtos.read_run_operations import (
    AllowanceCheck,
    ReadRunOperationsRequest,
)
from bugflow.review.usecases.read_run_operations import (
    ReadRunOperationsUseCase,
)
from bugflow.shared.domain.values.caller import Caller

#: The pages, kept beside this module.
RUN_PAGE = "operations_run_page.html"


class Clock(Protocol):
    def now(self) -> datetime: ...


@dataclass(frozen=True)
class OperationsReading:
    """What the operations routes are served with."""

    #: The role a caller needs to read them.
    role: str
    run: Callable[[], ReadRunOperationsUseCase]
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

    @app.get("/operations/run", response_class=HTMLResponse)
    def run_page() -> str:
        return files("bugflow.apps.api").joinpath(RUN_PAGE).read_text()
