"""Tests of what a pace layer is: a cadence, and the processes that run
at it.

A layer holds processes, not repositories, and a run works its subject
out from what the repositories declare. Nothing here takes a forge, a
repository or a clock.
"""

import pytest

from bugflow.method.domain.models.pace_layer import (
    CADENCES,
    EVENT,
    WEEKLY,
    Process,
    cadence,
    layer,
    process,
)

STOCKTAKE = Process(name="architecture-stocktake", subject="range")
REVIEW = Process(name="evaluate-pull-request", subject="pull request")
DECLARED = {one.name: one for one in (STOCKTAKE, REVIEW)}


def test_a_delivery_is_the_cadence_no_clock_fires() -> None:
    assert EVENT.on_a_clock is False


def test_every_other_cadence_is_fired_by_a_clock() -> None:
    clocked = {name for name, one in CADENCES.items() if one.on_a_clock}

    assert clocked == {
        "nightly",
        "weekly",
        "fortnightly",
        "monthly",
        "quarterly",
        "annual",
    }


def test_a_cadence_nobody_defined_is_refused() -> None:
    with pytest.raises(ValueError, match="sprintly"):
        cadence("sprintly")


def test_a_process_reads_a_pull_request_or_a_range() -> None:
    assert process("a", "range").subject == "range"
    assert process("b", "pull request").subject == "pull request"


def test_a_subject_nobody_defined_is_refused() -> None:
    with pytest.raises(ValueError, match="repository"):
        process("a", "repository")


def test_a_layer_holds_the_processes_it_names() -> None:
    weekly = layer("weekly", "weekly", ["architecture-stocktake"], DECLARED)

    assert weekly.cadence is WEEKLY
    assert weekly.processes == (STOCKTAKE,)


def test_a_layer_holding_no_process_is_refused() -> None:
    with pytest.raises(ValueError, match="holds no process"):
        layer("weekly", "weekly", [], DECLARED)


def test_a_layer_naming_a_process_nobody_declared_is_refused() -> None:
    with pytest.raises(ValueError, match="test-suite-stocktake"):
        layer("weekly", "weekly", ["test-suite-stocktake"], DECLARED)


def test_a_layer_is_the_same_whatever_order_it_names_its_processes() -> None:
    one = layer("pull-request", "event", list(DECLARED), DECLARED)
    other = layer(
        "pull-request", "event", list(reversed(list(DECLARED))), DECLARED
    )

    assert one == other
