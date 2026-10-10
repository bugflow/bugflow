"""Tests of when a dispatch is refused for money, and which allowance
refused it.

Every allowance that matches a run applies, and one measured over a
period is a question about what its scope has already spent. A day is a
calendar day in the timezone the server is set to count periods in,
which is UTC unless ``PERIODS_TIMEZONE`` says otherwise.
"""

from datetime import UTC, datetime, timedelta

import pytest

from bugflow.apps.worker.reviewers import (
    DEFAULT_PERIODS_TIMEZONE,
    Boundaries,
    ReviewerSettings,
    out_of_room,
    periods_timezone,
    refused_by,
)
from bugflow.method.domain.models.pace_layer import (
    EVENT,
    WEEKLY,
    PaceLayer,
    Process,
)
from bugflow.review.domain.models.cadence_boundary import (
    CadenceBoundary,
)
from bugflow.review.domain.models.layer_boundary import LayerBoundary
from bugflow.review.domain.models.spend_binding import (
    SpendBinding,
    SpendScope,
)
from bugflow.review.infrastructure.in_memory_cadence_boundaries import (
    InMemoryCadenceBoundaries,
)
from bugflow.review.infrastructure.in_memory_layer_boundaries import (
    InMemoryLayerBoundaries,
)
from bugflow.review.infrastructure.in_memory_spend_bindings import (
    InMemorySpendBindings,
)
from bugflow.review.infrastructure.in_memory_spend_record import (
    InMemorySpendRecord,
)
from bugflow.shared.domain.values.budget import Budget

# Four in the morning in UTC.
NOW = datetime(2026, 9, 25, 4, 0, tzinfo=UTC)
REPO = SpendScope(forge="github", repo="o/r")
LAYER = PaceLayer(
    name="weekly",
    cadence=WEEKLY,
    processes=(Process(name="stocktake", subject="range"),),
)


def settings() -> ReviewerSettings:
    return ReviewerSettings(
        agent_id="security",
        instructions="Read the week.",
        layer="weekly",
    )


def bound(
    usd: float | None, per: str = "nightly", scope: SpendScope = REPO
) -> InMemorySpendBindings:
    held = InMemorySpendBindings()
    held.declare(
        SpendBinding(scope=scope, budget=Budget(usd=usd, turns=None), per=per)
    )
    return held


def deployment(zone: str = DEFAULT_PERIODS_TIMEZONE) -> Boundaries:
    """What a deployment declares its periods begin on, counted in that
    timezone."""
    declared = InMemoryCadenceBoundaries()
    for cadence, at in (
        ("nightly", "00:00"),
        ("weekly", "MON 00:00"),
        ("monthly", "1 00:00"),
    ):
        declared.declare(CadenceBoundary(cadence=cadence, boundary=at))
    return Boundaries(layers={}, deployment=declared, zone=zone)


def spent(usd: float, at: datetime = NOW) -> InMemorySpendRecord:
    held = InMemorySpendRecord()
    held.costs = [("github", "o/r", "weekly", "security", at, usd)]
    return held


def test_a_days_allowance_with_room_refuses_nothing() -> None:
    found = refused_by(
        bound(10.0), spent(2.0), deployment(), NOW, "github", "o/r", settings()
    )
    assert found is None


def test_a_days_allowance_that_is_spent_refuses_and_says_which() -> None:
    """Not "out of budget": a reader given no scope goes to the wrong
    table."""
    found = refused_by(
        bound(10.0),
        spent(10.0),
        deployment(),
        NOW,
        "github",
        "o/r",
        settings(),
    )
    assert found is not None
    assert "github:o/r" in found
    assert "$10.00 per nightly" in found
    assert "has spent $10.00" in found


def test_an_invocation_allowance_is_not_a_period_question() -> None:
    """It is the ceiling handed to the run, and the vendor holds the run
    to it. Nothing here asks what an invocation has already spent."""
    found = refused_by(
        bound(1.0, per="event"),
        spent(500.0),
        deployment(),
        NOW,
        "github",
        "o/r",
        settings(),
    )
    assert found is None


def test_an_unlimited_allowance_refuses_nothing() -> None:
    found = refused_by(
        bound(None),
        spent(9999.0),
        deployment(),
        NOW,
        "github",
        "o/r",
        settings(),
    )
    assert found is None


def test_yesterdays_spending_is_not_todays() -> None:
    """A calendar day resets, which is what a person means by ten
    dollars a day."""
    yesterday = NOW - timedelta(days=1)
    found = refused_by(
        bound(10.0),
        spent(10.0, at=yesterday),
        deployment(),
        NOW,
        "github",
        "o/r",
        settings(),
    )
    assert found is None


def test_a_deployment_that_cannot_answer_refuses_nothing() -> None:
    """Without the spend record there is no question to ask, and a
    deployment that cannot ask it is not thereby over every limit."""
    assert refused_by(
        bound(1.0), None, deployment(), NOW, "github", "o/r", settings()
    ) is (None)
    assert refused_by(
        None, spent(9.0), deployment(), NOW, "github", "o/r", settings()
    ) is (None)


def test_a_repositorys_own_boundary_bounds_its_own_allowance() -> None:
    """Where the scope names one repository and one layer riding the
    cadence it is counted per, that repository's declaration answers."""
    repositories = InMemoryLayerBoundaries()
    repositories.declare(
        LayerBoundary(
            forge="github", repo="o/r", layer="weekly", boundary="SUN 23:30"
        )
    )
    boundaries = Boundaries(
        layers={"weekly": LAYER},
        repositories=repositories,
        deployment=deployment().deployment,
    )
    scoped = SpendScope(forge="github", repo="o/r", layer="weekly")

    assert (
        boundaries.bounding(
            SpendBinding(
                scope=scoped,
                budget=Budget(usd=1.0, turns=None),
                per="weekly",
            )
        )
        == "SUN 23:30"
    )


def test_an_allowance_over_everything_reads_the_deployments() -> None:
    """A weekly ceiling over everything covers every repository there
    is, so no repository's decision answers for it."""
    boundaries = Boundaries(
        layers={"weekly": LAYER}, deployment=deployment().deployment
    )

    assert (
        boundaries.bounding(
            SpendBinding(
                scope=SpendScope(),
                budget=Budget(usd=150.0, turns=None),
                per="weekly",
            )
        )
        == "MON 00:00"
    )


def test_a_layer_of_another_cadence_does_not_bound_it() -> None:
    """A binding may name a layer and a cadence that have nothing to do
    with each other. The layer answers only if it rides the cadence
    being counted."""
    repositories = InMemoryLayerBoundaries()
    repositories.declare(
        LayerBoundary(
            forge="github", repo="o/r", layer="weekly", boundary="SUN 23:30"
        )
    )
    boundaries = Boundaries(
        layers={"weekly": LAYER},
        repositories=repositories,
        deployment=deployment().deployment,
    )
    scoped = SpendScope(forge="github", repo="o/r", layer="weekly")

    assert (
        boundaries.bounding(
            SpendBinding(
                scope=scoped,
                budget=Budget(usd=8.0, turns=None),
                per="nightly",
            )
        )
        == "00:00"
    )


def test_a_ceiling_nothing_can_count_refuses_rather_than_lapses() -> None:
    """A ceiling nobody can measure is not a ceiling that does not
    apply: spending under a limit nothing is measuring is what this
    exists to stop."""
    found = refused_by(
        bound(10.0),
        spent(1.0),
        Boundaries(layers={}),
        NOW,
        "github",
        "o/r",
        settings(),
    )

    assert found is not None
    assert "nothing says where a nightly period begins" in found


def test_an_event_allowance_is_not_a_question_about_a_window() -> None:
    """The cadence no clock fires has no span, so a per-event allowance
    is the ceiling handed to the run rather than a question asked
    first."""
    assert (
        Boundaries(layers={}).window(
            SpendBinding(
                scope=REPO,
                budget=Budget(usd=1.0, turns=None),
                per=EVENT.name,
            ),
            NOW,
        )
        is None
    )


def test_a_scope_with_no_reviewer_can_be_asked() -> None:
    """Judging spends and names no reviewer. A backfill judges every
    pull request it reads, so the question is asked of a scope."""
    found = out_of_room(
        bound(10.0), spent(10.0), deployment(), NOW, "github", "o/r"
    )
    assert found is not None
    assert "github:o/r" in found


def test_a_repository_with_room_is_not_refused_its_judging() -> None:
    assert (
        out_of_room(
            bound(10.0), spent(1.0), deployment(), NOW, "github", "o/r"
        )
        is None
    )


def test_periods_are_counted_in_utc_unless_a_setting_says_otherwise() -> None:
    assert periods_timezone({}) == "UTC"
    assert periods_timezone({"PERIODS_TIMEZONE": ""}) == "UTC"
    assert Boundaries(layers={}).zone == "UTC"


def test_the_setting_names_the_timezone_periods_are_counted_in() -> None:
    assert (
        periods_timezone({"PERIODS_TIMEZONE": "Pacific/Auckland"})
        == "Pacific/Auckland"
    )


def test_a_setting_that_is_not_a_timezone_stops_the_program() -> None:
    with pytest.raises(ValueError, match="PERIODS_TIMEZONE is 'Nowhere/No'"):
        periods_timezone({"PERIODS_TIMEZONE": "Nowhere/No"})


def test_a_day_begins_where_the_timezone_says_it_does() -> None:
    """One in the afternoon of the 24th in UTC is the day before in UTC,
    and already the 25th twelve hours east of it. So the same spending
    is yesterday's on one server and today's on another."""
    earlier = datetime(2026, 9, 24, 13, 0, tzinfo=UTC)
    counted_in_utc = refused_by(
        bound(10.0),
        spent(10.0, at=earlier),
        deployment(),
        NOW,
        "github",
        "o/r",
        settings(),
    )
    counted_east = refused_by(
        bound(10.0),
        spent(10.0, at=earlier),
        deployment(periods_timezone({"PERIODS_TIMEZONE": "Pacific/Auckland"})),
        NOW,
        "github",
        "o/r",
        settings(),
    )
    assert counted_in_utc is None
    assert counted_east is not None
    assert "has spent $10.00" in counted_east
