"""Tests of which schedules a topology, the watched repositories and
their boundaries ask for.

A stocktake is started by a clock and not by a delivery, so one
schedule fires each layer whose cadence is on a clock, for each watched
repository. When one fires is declared for each repository and layer,
and read in the timezone the caller gives.
"""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleAlreadyRunningError,
    ScheduleCalendarSpec,
    ScheduleSpec,
)

from bugflow.apps.worker.schedules import (
    Scheduled,
    TemporalScheduler,
    reconcile,
    spec_for,
    wanted_schedules,
)
from bugflow.method.domain.models.boundary import BoundaryError
from bugflow.method.domain.models.pace_layer import (
    CADENCES,
    EVENT,
    layer,
    process,
)
from bugflow.review.domain.models.layer_boundary import LayerBoundary
from bugflow.review.dtos.take_stock import TakeStockRequest
from bugflow.review.infrastructure.in_memory_layer_boundaries import (
    InMemoryLayerBoundaries,
)
from bugflow.shared.domain.values.correlation import Correlation

NOW = datetime(2030, 3, 12, 4, 0, tzinfo=UTC)
#: The timezone the boundaries are read in.
ZONE = "Europe/Lisbon"

STOCKTAKE = process("security-stocktake", "range", reviewer="security")
EVALUATE = process("evaluate-pull-request", "pull request")
WEEKLY = layer(
    "weekly",
    "weekly",
    ["security-stocktake"],
    {"security-stocktake": STOCKTAKE},
)
ON_EVENT = layer(
    "pull-request",
    "event",
    ["evaluate-pull-request"],
    {"evaluate-pull-request": EVALUATE},
)
WATCHED = ("github:example-org/widgets", "github:example-org/gadgets")


def declared(*rows: tuple[str, str, str]) -> InMemoryLayerBoundaries:
    held = InMemoryLayerBoundaries()
    for repo, on, at in rows:
        held.declare(
            LayerBoundary(forge="github", repo=repo, layer=on, boundary=at)
        )
    return held


def weekly_at(at: str = "SUN 23:30") -> InMemoryLayerBoundaries:
    return declared(
        ("example-org/widgets", "weekly", at),
        ("example-org/gadgets", "weekly", at),
    )


def test_a_layer_on_a_clock_is_scheduled_for_every_watched_repository() -> (
    None
):
    wanted = wanted_schedules({"weekly": WEEKLY}, WATCHED, weekly_at())

    assert sorted(wanted) == [
        "stocktake/github/example-org/gadgets/weekly",
        "stocktake/github/example-org/widgets/weekly",
    ]
    assert wanted["stocktake/github/example-org/widgets/weekly"] == Scheduled(
        schedule_id="stocktake/github/example-org/widgets/weekly",
        forge="github",
        repo="example-org/widgets",
        layer="weekly",
        cadence=CADENCES["weekly"],
        boundary="SUN 23:30",
    )


def test_a_layer_a_delivery_fires_is_scheduled_by_nothing() -> None:
    """A schedule that fires what a webhook already starts pays twice for
    one evaluation."""
    assert (
        wanted_schedules({"pull-request": ON_EVENT}, WATCHED, weekly_at())
        == {}
    )


def test_nothing_watched_is_nothing_scheduled() -> None:
    assert wanted_schedules({"weekly": WEEKLY}, (), weekly_at()) == {}


def test_a_repository_with_no_boundary_is_not_fired_on_a_guess() -> None:
    """The worker refuses to start on one, so this is what a boundary
    withdrawn while it ran leaves behind."""
    only_one = declared(("example-org/widgets", "weekly", "SUN 23:30"))

    assert sorted(wanted_schedules({"weekly": WEEKLY}, WATCHED, only_one)) == [
        "stocktake/github/example-org/widgets/weekly"
    ]


def test_two_repositories_on_one_cadence_fire_where_each_declared() -> None:
    """One calendar for each cadence could not say this."""
    boundaries = declared(
        ("example-org/widgets", "weekly", "SUN 23:30"),
        ("example-org/gadgets", "weekly", "TUE 09:00"),
    )
    wanted = wanted_schedules({"weekly": WEEKLY}, WATCHED, boundaries)

    (mine,) = spec_for(
        CADENCES["weekly"],
        wanted["stocktake/github/example-org/widgets/weekly"].boundary,
        NOW,
        ZONE,
    ).calendars
    (theirs,) = spec_for(
        CADENCES["weekly"],
        wanted["stocktake/github/example-org/gadgets/weekly"].boundary,
        NOW,
        ZONE,
    ).calendars

    assert [one.start for one in mine.day_of_week] == [0]
    assert [one.start for one in mine.hour] == [23]
    assert [one.start for one in theirs.day_of_week] == [2]
    assert [one.start for one in theirs.hour] == [9]


def test_a_boundary_is_read_in_the_timezone_given() -> None:
    """The cadence is the method's. When it fires is declared, and it is
    read as a Sunday night in the server's timezone and not in UTC."""
    spec = spec_for(CADENCES["weekly"], "SUN 23:30", NOW, ZONE)
    (calendar,) = spec.calendars

    assert [one.start for one in calendar.day_of_week] == [0]
    assert [one.start for one in calendar.minute] == [30]
    assert spec.time_zone_name == ZONE
    assert (
        spec_for(CADENCES["weekly"], "SUN 23:30", NOW, "UTC").time_zone_name
        == "UTC"
    )


def test_a_cadence_no_clock_fires_has_no_schedule() -> None:
    """A layer nobody can fire is a layer that silently never runs."""
    with pytest.raises(ValueError, match="event"):
        spec_for(EVENT, "60s", NOW, ZONE)


BOUNDED = {
    "nightly": "23:30",
    "weekly": "SUN 23:30",
    "fortnightly": "2030-03-13 00:00",
    "monthly": "1 23:30",
    "quarterly": "2030-07-01 00:00",
    "annual": "2030-07-01 00:00",
}


@pytest.mark.parametrize("name,at", BOUNDED.items(), ids=list(BOUNDED))
def test_every_clock_cadence_can_be_fired(name: str, at: str) -> None:
    """A topology the worker accepts would otherwise declare a layer
    nothing fires."""
    spec = spec_for(CADENCES[name], at, NOW, ZONE)

    assert spec.calendars or spec.intervals


def test_a_quarterly_layer_fires_four_times_a_year() -> None:
    """In the month its boundary names and every third month after it,
    where an annual layer fires in that month alone."""
    (quarterly,) = spec_for(
        CADENCES["quarterly"], "2030-07-01 00:00", NOW, ZONE
    ).calendars
    (annual,) = spec_for(
        CADENCES["annual"], "2030-07-01 00:00", NOW, ZONE
    ).calendars

    assert sorted(r.start for r in quarterly.month) == [1, 4, 7, 10]
    assert [r.start for r in annual.month] == [7]


def test_a_fortnight_fires_on_an_interval_and_not_a_calendar() -> None:
    """Every second Wednesday is not a calendar a scheduler can state: it
    is a length and a starting point, which is what an interval is."""
    spec = spec_for(CADENCES["fortnightly"], "2030-03-13 00:00", NOW, ZONE)

    assert not spec.calendars
    (interval,) = spec.intervals
    assert interval.every == timedelta(days=14)
    assert interval.offset is not None
    assert interval.offset < timedelta(days=14)


def test_a_boundary_that_is_no_boundary_is_refused() -> None:
    with pytest.raises(BoundaryError):
        spec_for(CADENCES["weekly"], "every other tuesday", NOW, ZONE)


class FakeScheduler:
    """A scheduler that remembers what it was asked for."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, str, str]] = []

    async def ensure_schedule(
        self,
        *,
        schedule_id: str,
        spec: object,
        task_queue: str,
        request: object,
    ) -> None:
        self.asked.append(
            (schedule_id, task_queue, request.layer)  # type: ignore[attr-defined]
        )


def test_reconciling_creates_one_schedule_per_layer_and_repository() -> None:
    scheduler = FakeScheduler()
    made = asyncio.run(
        reconcile(
            scheduler,
            {"weekly": WEEKLY},
            WATCHED,
            "a-queue",
            weekly_at(),
            NOW,
            ZONE,
        )
    )

    assert made == [
        "stocktake/github/example-org/gadgets/weekly",
        "stocktake/github/example-org/widgets/weekly",
    ]
    assert [one[2] for one in scheduler.asked] == ["weekly", "weekly"]
    assert {one[1] for one in scheduler.asked} == {"a-queue"}


def test_reconciling_a_delivery_layer_asks_for_nothing() -> None:
    scheduler = FakeScheduler()

    assert (
        asyncio.run(
            reconcile(
                scheduler,
                {"pull-request": ON_EVENT},
                WATCHED,
                "q",
                weekly_at(),
                NOW,
                ZONE,
            )
        )
        == []
    )
    assert scheduler.asked == []


class FakeHandle:
    """One schedule on a fake server, describable and updatable."""

    def __init__(self, held: "FakeServer", schedule_id: str) -> None:
        self._held = held
        self._id = schedule_id

    async def describe(self) -> object:
        return SimpleNamespace(schedule=self._held.schedules[self._id])

    async def update(self, onto: Callable[[object], object]) -> None:
        described = SimpleNamespace(schedule=self._held.schedules[self._id])
        answered = onto(SimpleNamespace(description=described))
        self._held.schedules[self._id] = answered.schedule  # type: ignore[attr-defined]
        self._held.updated.append(self._id)


class FakeServer:
    """A scheduler server that already holds what it was given."""

    def __init__(self, schedules: dict[str, object] | None = None) -> None:
        self.schedules: dict[str, object] = dict(schedules or {})
        self.updated: list[str] = []

    async def create_schedule(
        self, schedule_id: str, schedule: object
    ) -> None:
        if schedule_id in self.schedules:
            raise ScheduleAlreadyRunningError()
        self.schedules[schedule_id] = schedule

    def get_schedule_handle(self, schedule_id: str) -> FakeHandle:
        return FakeHandle(self, schedule_id)


def held_on(spec: ScheduleSpec) -> Schedule:
    return Schedule(
        action=ScheduleActionStartWorkflow(
            "StocktakeWorkflow",
            TakeStockRequest(
                forge="github",
                repo="example-org/widgets",
                layer="weekly",
                correlation=Correlation(workflow_id="", run_id=""),
            ),
            id="stocktake/github/example-org/widgets/weekly/run",
            task_queue="a-queue",
        ),
        spec=spec,
    )


def scheduling(server: FakeServer) -> TemporalScheduler:
    return TemporalScheduler(server, "StocktakeWorkflow")  # type: ignore[arg-type]


def ask(scheduler: TemporalScheduler, spec: ScheduleSpec) -> None:
    asyncio.run(
        scheduler.ensure_schedule(
            schedule_id="stocktake/github/example-org/widgets/weekly",
            spec=spec,
            task_queue="a-queue",
            request=TakeStockRequest(
                forge="github",
                repo="example-org/widgets",
                layer="weekly",
                correlation=Correlation(workflow_id="", run_id=""),
            ),
        )
    )


def test_a_schedule_already_firing_on_its_boundary_is_left_alone() -> None:
    """Its next firing belongs to the server, and rewriting one on every
    worker start would move it."""
    wanted = spec_for(CADENCES["weekly"], "SUN 23:30", NOW, ZONE)
    server = FakeServer(
        {"stocktake/github/example-org/widgets/weekly": held_on(wanted)}
    )

    ask(scheduling(server), wanted)

    assert server.updated == []


def test_a_schedule_firing_on_something_else_is_moved_onto_it() -> None:
    """Declaring a boundary would otherwise change nothing for a
    schedule made before it."""
    was = spec_for(CADENCES["weekly"], "MON 00:00", NOW, ZONE)
    server = FakeServer(
        {"stocktake/github/example-org/widgets/weekly": held_on(was)}
    )
    wanted = spec_for(CADENCES["weekly"], "SUN 23:30", NOW, ZONE)

    ask(scheduling(server), wanted)

    assert server.updated == ["stocktake/github/example-org/widgets/weekly"]
    held = server.schedules["stocktake/github/example-org/widgets/weekly"]
    assert held.spec == wanted  # type: ignore[attr-defined]


def test_a_schedule_that_is_not_there_is_created() -> None:
    server = FakeServer()

    ask(
        scheduling(server),
        spec_for(CADENCES["weekly"], "SUN 23:30", NOW, ZONE),
    )

    assert list(server.schedules) == [
        "stocktake/github/example-org/widgets/weekly"
    ]
    assert server.updated == []


def as_the_server_answers(spec: ScheduleSpec) -> ScheduleSpec:
    """The same spec as a round trip through the server returns it.

    Every range comes back as a tuple. A spec built here carries lists
    for the fields it sets, and the dataclasses compare those unequal.
    """
    return ScheduleSpec(
        calendars=tuple(
            ScheduleCalendarSpec(
                second=tuple(one.second),
                minute=tuple(one.minute),
                hour=tuple(one.hour),
                day_of_month=tuple(one.day_of_month),
                month=tuple(one.month),
                year=tuple(one.year),
                day_of_week=tuple(one.day_of_week),
                comment=one.comment,
            )
            for one in spec.calendars
        ),
        intervals=tuple(spec.intervals),
        time_zone_name=spec.time_zone_name,
    )


def test_a_schedule_the_server_answers_alike_is_left_alone() -> None:
    """The server returns tuples where a spec built here holds lists.
    Compared as the dataclasses compare, that is a different schedule,
    and every worker start would rewrite every schedule it found."""
    wanted = spec_for(CADENCES["weekly"], "SUN 23:30", NOW, ZONE)
    server = FakeServer(
        {
            "stocktake/github/example-org/widgets/weekly": held_on(
                as_the_server_answers(wanted)
            )
        }
    )

    ask(scheduling(server), wanted)

    assert server.updated == []


def test_an_interval_schedule_the_server_answers_alike_is_left_alone() -> None:
    wanted = spec_for(CADENCES["fortnightly"], "2030-03-13 00:00", NOW, ZONE)
    server = FakeServer(
        {
            "stocktake/github/example-org/widgets/weekly": held_on(
                as_the_server_answers(wanted)
            )
        }
    )

    ask(scheduling(server), wanted)

    assert server.updated == []
