"""The stocktake schedules a topology asks for, and when each fires.

A pull request's evaluation is started by a delivery. A stocktake has
no delivery, so a schedule starts it: one for each layer whose cadence
is on a clock, for each repository this server watches.

Which cadences exist is the method's, in the topology. Where a
repository's periods begin is declared for each repository and layer.
The timezone a boundary is read in is this server's ``PERIODS_TIMEZONE``
setting, which the caller passes as ``zone``.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleCalendarSpec,
    ScheduleIntervalSpec,
    ScheduleRange,
    ScheduleSpec,
    ScheduleUpdate,
    ScheduleUpdateInput,
)
from temporalio.service import RPCError, RPCStatusCode

from bugflow.method.domain.models.boundary import phase
from bugflow.method.domain.models.pace_layer import Cadence, PaceLayer
from bugflow.review.domain.services.layer_boundaries import (
    LayerBoundariesService,
)
from bugflow.review.dtos.take_stock import TakeStockRequest
from bugflow.shared.domain.values.correlation import Correlation

#: What every stocktake schedule's id begins with. A schedule with it,
#: on this worker's task queue, that the topology no longer asks for is
#: deleted.
STOCKTAKE_SCHEDULE = "stocktake/"

#: The months a quarter fires in, counted from the month its boundary
#: names: that month and every third one after it.
_QUARTERS = (0, 3, 6, 9)


def _every(values: tuple[int, ...]) -> list[ScheduleRange]:
    return [ScheduleRange(value) for value in values]


def _calendar(at: datetime, span: str) -> ScheduleCalendarSpec:
    """Return one firing for each period, at the instant its boundary
    names.

    Which parts of the instant matter is the span's: a day cares about
    the time, a week about the weekday too, a month about the day of the
    month, a year about the month as well.
    """
    hour, minute = _every((at.hour,)), _every((at.minute,))
    if span == "day":
        return ScheduleCalendarSpec(hour=hour, minute=minute)
    if span == "week":
        # Temporal counts Sunday as 0; datetime counts Monday as 0.
        return ScheduleCalendarSpec(
            day_of_week=_every(((at.weekday() + 1) % 7,)),
            hour=hour,
            minute=minute,
        )
    if span == "month":
        return ScheduleCalendarSpec(
            day_of_month=_every((at.day,)), hour=hour, minute=minute
        )
    if span == "quarter":
        return ScheduleCalendarSpec(
            day_of_month=_every((at.day,)),
            month=_every(
                tuple((at.month - 1 + step) % 12 + 1 for step in _QUARTERS)
            ),
            hour=hour,
            minute=minute,
        )
    if span == "year":
        return ScheduleCalendarSpec(
            day_of_month=_every((at.day,)),
            month=_every((at.month,)),
            hour=hour,
            minute=minute,
        )
    raise ValueError(f"{span!r} is no span a schedule can fire on")


def spec_for(
    cadence: Cadence, boundary: str, now: datetime, zone: str
) -> ScheduleSpec:
    """Return when that layer fires for that repository, from its
    boundary, read in the timezone ``zone``.

    A cadence says how often. The declared boundary says where its
    periods begin, and a stocktake fires when one does. One calendar
    for each cadence could not say that two repositories on one cadence
    read on different days.

    A fortnight is an interval and not a calendar, because every second
    Wednesday is not a calendar a scheduler can state: it is a length
    and a starting point, and an interval is both. Temporal counts an
    interval from the epoch, so the offset is how far the boundary sits
    into one.

    Raises ``ValueError`` for a cadence no clock fires, and
    ``BoundaryError`` for a boundary that cannot be read.
    """
    if not cadence.on_a_clock:
        raise ValueError(
            f"{cadence.name!r} is fired by no clock, so it has no schedule"
        )
    at = phase(boundary, cadence.span, now, zone).at
    if cadence.span == "fortnight":
        length = timedelta(days=14)
        since = at.astimezone(UTC) - datetime(1970, 1, 1, tzinfo=UTC)
        return ScheduleSpec(
            intervals=[
                ScheduleIntervalSpec(every=length, offset=since % length)
            ]
        )
    return ScheduleSpec(
        calendars=[_calendar(at, cadence.span)], time_zone_name=zone
    )


def _levelled(spec: ScheduleSpec) -> tuple[object, ...]:
    """Return a spec's content with every list made a tuple, for
    comparing.

    The server answers with tuples and a spec built here carries lists,
    and the dataclasses compare those unequal field by field. Compared
    as they are, every schedule would look changed and every worker
    start would rewrite every schedule it found.
    """
    return (
        tuple(
            (
                tuple(calendar.second),
                tuple(calendar.minute),
                tuple(calendar.hour),
                tuple(calendar.day_of_month),
                tuple(calendar.month),
                tuple(calendar.year),
                tuple(calendar.day_of_week),
                calendar.comment,
            )
            for calendar in spec.calendars
        ),
        tuple(
            (interval.every, interval.offset) for interval in spec.intervals
        ),
        spec.time_zone_name,
    )


class ScheduleClient(Protocol):
    """What reconciling needs of a scheduler: one call that makes a
    schedule, and may be repeated, and the two that find and delete one
    nothing asks for any more."""

    async def ensure_schedule(
        self,
        *,
        schedule_id: str,
        spec: ScheduleSpec,
        task_queue: str,
        request: TakeStockRequest,
    ) -> None: ...

    async def stocktake_schedules(self, task_queue: str) -> list[str]:
        """The id of each stocktake schedule that starts its workflow on
        that task queue."""
        ...

    async def delete_schedule(self, schedule_id: str) -> None: ...


@dataclass(frozen=True, kw_only=True)
class Reconciled:
    """What reconciling did: the schedules the topology asks for, each
    made or kept, and those it deleted."""

    scheduled: list[str]
    deleted: list[str]


@dataclass(frozen=True, kw_only=True)
class Scheduled:
    """One schedule: which layer takes stock of which repository."""

    schedule_id: str
    forge: str
    repo: str
    layer: str
    cadence: Cadence
    #: Where this repository's periods on this layer begin, as declared.
    #: A schedule fires when one does.
    boundary: str


def wanted_schedules(
    layers: Mapping[str, PaceLayer],
    watched: Iterable[str],
    boundaries: LayerBoundariesService,
) -> dict[str, Scheduled]:
    """Return every schedule this topology and these repositories ask
    for, by schedule id. ``watched`` names each repository as
    ``forge:owner/repo``.

    A layer a delivery fires is scheduled by nothing: a schedule beside
    the webhook would pay twice for one evaluation.

    Each carries the boundary its repository declared for that layer,
    which is when it fires. A pair with none is left out and not fired
    on a guess. The worker refuses to start on one, so this sees it
    only if a boundary was withdrawn while the worker ran.
    """
    repositories = [one for one in watched if one]
    wanted: dict[str, Scheduled] = {}
    for layer in layers.values():
        if not layer.cadence.on_a_clock:
            continue
        for watched_repository in repositories:
            forge, _, repo = watched_repository.partition(":")
            declared = boundaries.boundary(forge, repo, layer.name)
            if declared is None:
                continue
            schedule_id = f"{STOCKTAKE_SCHEDULE}{forge}/{repo}/{layer.name}"
            wanted[schedule_id] = Scheduled(
                schedule_id=schedule_id,
                forge=forge,
                repo=repo,
                layer=layer.name,
                cadence=layer.cadence,
                boundary=declared,
            )
    return wanted


async def reconcile(
    client: "ScheduleClient",
    layers: Mapping[str, PaceLayer],
    watched: Iterable[str],
    task_queue: str,
    boundaries: LayerBoundariesService,
    now: datetime,
    zone: str,
) -> Reconciled:
    """Create the schedules the topology asks for, delete those on this
    task queue it no longer asks for, and say which are which.

    A schedule already there keeps its next firing, which is the
    server's business, unless what it fires on has changed: a boundary
    declared after the schedule was made would otherwise reach nothing.
    A layer whose cadence no clock fires is not scheduled.

    A schedule nothing asks for is one whose repository no gnome judges
    any more, whose layer the deployment in force no longer holds or
    puts on a clock, or whose boundary was withdrawn. Left, it would
    go on starting stocktakes, and a stocktake dispatches whatever the
    repository is still set to.
    """
    wanted = wanted_schedules(layers, watched, boundaries)
    for schedule_id, one in sorted(wanted.items()):
        await client.ensure_schedule(
            schedule_id=schedule_id,
            spec=spec_for(one.cadence, one.boundary, now, zone),
            task_queue=task_queue,
            request=TakeStockRequest(
                forge=one.forge,
                repo=one.repo,
                layer=one.layer,
                # Empty on purpose: one request serves every firing, so
                # nothing here can name a run. The workflow fills it from
                # its own execution.
                correlation=Correlation(workflow_id="", run_id=""),
            ),
        )
    deleted = sorted(
        set(await client.stocktake_schedules(task_queue)) - set(wanted)
    )
    for schedule_id in deleted:
        await client.delete_schedule(schedule_id)
    return Reconciled(scheduled=sorted(wanted), deleted=deleted)


class TemporalScheduler:
    """Implements ``ScheduleClient`` with Temporal's schedules.

    Creating a schedule that is already there raises, and that is the
    ordinary case: every worker start reconciles. The existing schedule
    is kept, because its next firing belongs to the server and making
    it again would move it.

    It raises in one of two ways. Asked once, the server answers that
    the schedule is already running, which the SDK raises as its own
    error. Asked again by the client's retry, after a first attempt the
    server carried out but answered with an error, such as having too
    few hosts while it starts, it answers the retry with a bare
    ``ALREADY_EXISTS``. Both say the schedule is there.
    """

    def __init__(self, client: Client, workflow: str) -> None:
        self._client = client
        self._workflow = workflow

    async def ensure_schedule(
        self,
        *,
        schedule_id: str,
        spec: ScheduleSpec,
        task_queue: str,
        request: TakeStockRequest,
    ) -> None:
        try:
            await self._client.create_schedule(
                schedule_id,
                Schedule(
                    action=ScheduleActionStartWorkflow(
                        self._workflow,
                        request,
                        id=f"{schedule_id}/run",
                        task_queue=task_queue,
                    ),
                    spec=spec,
                ),
            )
        except ScheduleAlreadyRunningError:
            await self._retime(schedule_id, spec)
        except RPCError as exc:
            if exc.status != RPCStatusCode.ALREADY_EXISTS:
                raise
            await self._retime(schedule_id, spec)

    async def stocktake_schedules(self, task_queue: str) -> list[str]:
        """Each stocktake schedule on that task queue. The listing does
        not carry the task queue, so each is described.

        The listing lags the server, so it can name a schedule already
        deleted, which is left out. A server that does not implement
        schedules, as Temporal's time-skipping test server does not,
        holds none.
        """
        try:
            listed = [
                one.id
                async for one in await self._client.list_schedules()
                if one.id.startswith(STOCKTAKE_SCHEDULE)
            ]
        except RPCError as exc:
            if exc.status == RPCStatusCode.UNIMPLEMENTED:
                return []
            raise
        found = []
        for schedule_id in listed:
            try:
                described = await self._client.get_schedule_handle(
                    schedule_id
                ).describe()
            except RPCError as exc:
                if exc.status == RPCStatusCode.NOT_FOUND:
                    continue
                raise
            action = described.schedule.action
            if (
                isinstance(action, ScheduleActionStartWorkflow)
                and action.task_queue == task_queue
            ):
                found.append(schedule_id)
        return found

    async def delete_schedule(self, schedule_id: str) -> None:
        """Delete it. One already gone is not an error."""
        try:
            await self._client.get_schedule_handle(schedule_id).delete()
        except RPCError as exc:
            if exc.status != RPCStatusCode.NOT_FOUND:
                raise

    async def _retime(self, schedule_id: str, spec: ScheduleSpec) -> None:
        """Move an existing schedule onto the spec it should fire on.

        Left alone while it matches, because its next firing belongs to
        the server and rewriting one on every worker start would move
        it. Rewritten if it does not, because declaring a boundary
        would otherwise change nothing for a schedule made before it.

        Compared on content and not as the dataclasses compare, which
        counts a list and a tuple of the same ranges as different specs.
        """
        handle = self._client.get_schedule_handle(schedule_id)
        described = await handle.describe()
        if _levelled(described.schedule.spec) == _levelled(spec):
            return

        def onto(update: ScheduleUpdateInput) -> ScheduleUpdate:
            update.description.schedule.spec = spec
            return ScheduleUpdate(schedule=update.description.schedule)

        await handle.update(onto)
