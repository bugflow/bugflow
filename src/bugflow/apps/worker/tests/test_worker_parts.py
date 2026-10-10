"""Tests of ``WorkerParts``: what a worker is assembled from, and how
two parts are added."""

import asyncio

from temporalio.client import Client

from bugflow.apps.worker.parts import WorkerParts
from bugflow.apps.worker.worker import WorkerParts as FromTheWorker


class One:
    """A stand-in for a workflow class."""


class Two:
    """Another."""


def first() -> None: ...


def second() -> None: ...


async def a_schedule(client: Client, task_queue: str) -> None: ...


async def a_watcher(stop: asyncio.Event) -> None: ...


def test_the_worker_module_offers_the_same_class() -> None:
    assert FromTheWorker is WorkerParts


def test_no_parts_serve_nothing() -> None:
    assert WorkerParts() + WorkerParts() == WorkerParts()
    assert not WorkerParts().serves


def test_each_field_of_a_sum_holds_the_firsts_entries_then_the_seconds() -> (
    None
):
    left = WorkerParts(
        workflows=(One,),
        activities=(first,),
        judging=(first,),
        schedules=(a_schedule,),
        before_serving=(first,),
        watchers=(a_watcher,),
        interceptors=("tracing",),
        lines=("indexes",),
    )
    right = WorkerParts(
        workflows=(Two,),
        activities=(second,),
        judging=(second,),
        before_serving=(second,),
        interceptors=("metrics",),
        lines=("reviews",),
    )

    both = left + right

    assert both.workflows == (One, Two)
    assert both.activities == (first, second)
    assert both.judging == (first, second)
    assert both.schedules == (a_schedule,)
    assert both.before_serving == (first, second)
    assert both.watchers == (a_watcher,)
    assert both.interceptors == ("tracing", "metrics")
    assert both.lines == ("indexes", "reviews")


def test_a_class_of_models_queue_serves_both_parts_activities() -> None:
    left = WorkerParts(assessing={"small": (first,), "large": (first,)})
    right = WorkerParts(assessing={"small": (second,), "medium": (second,)})

    both = left + right

    assert both.assessing == {
        "small": (first, second),
        "large": (first,),
        "medium": (second,),
    }
    assert left.assessing == {"small": (first,), "large": (first,)}


def test_adding_changes_neither_part() -> None:
    left, right = WorkerParts(lines=("a",)), WorkerParts(lines=("b",))
    assert (left + right).lines == ("a", "b")
    assert (left.lines, right.lines) == (("a",), ("b",))


def test_a_part_with_any_activity_serves() -> None:
    assert WorkerParts(workflows=(One,)).serves
    assert WorkerParts(activities=(first,)).serves
    assert WorkerParts(judging=(first,)).serves
    assert WorkerParts(assessing={"small": (first,)}).serves
    assert not WorkerParts(assessing={"small": ()}).serves
    assert not WorkerParts(watchers=(a_watcher,), lines=("a",)).serves
