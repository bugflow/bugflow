"""What a worker is assembled from.

A worker serves several things: the archive's search index, the review
workflows, and whatever a program built on this package adds. Each is
described as a ``WorkerParts``, and the worker runs the sum of them.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from temporalio.client import Client


@dataclass(frozen=True)
class WorkerParts:
    """Workflows and activities to register, and what to do around them.

    Two parts are added with ``+``. Each field of the sum holds the
    first part's entries and then the second's.
    """

    #: The workflow classes the task queue runs.
    workflows: tuple[type, ...] = ()
    #: The activities the task queue serves.
    activities: tuple[Callable[..., Any], ...] = ()
    #: The activities the rate-limited queue beside it serves.
    judging: tuple[Callable[..., Any], ...] = ()
    #: By class of model: the activities that class's queue serves.
    assessing: Mapping[str, tuple[Callable[..., Any], ...]] = field(
        default_factory=dict
    )
    #: Called once, after the worker connects, with the client and the
    #: task queue's name. Each makes the schedules its part needs.
    schedules: tuple[Callable[[Client, str], Awaitable[None]], ...] = ()
    #: Called once, before the worker serves anything. Each raises
    #: ``ValueError`` to stop a worker that must not start.
    before_serving: tuple[Callable[[], None], ...] = ()
    #: Run in the background while the worker serves, each given the
    #: event that stops the worker. One sets it to stop the worker.
    watchers: tuple[Callable[[asyncio.Event], Awaitable[None]], ...] = ()
    #: Temporal interceptors for the client the worker connects with,
    #: which a program built on this package uses for tracing.
    interceptors: tuple[Any, ...] = ()
    #: Lines printed when the worker starts serving.
    lines: tuple[str, ...] = ()

    def __add__(self, other: "WorkerParts") -> "WorkerParts":
        assessing = {
            name: tuple(held) for name, held in self.assessing.items()
        }
        for name, held in other.assessing.items():
            assessing[name] = (*assessing.get(name, ()), *held)
        return WorkerParts(
            workflows=self.workflows + other.workflows,
            activities=self.activities + other.activities,
            judging=self.judging + other.judging,
            assessing=assessing,
            schedules=self.schedules + other.schedules,
            before_serving=self.before_serving + other.before_serving,
            watchers=self.watchers + other.watchers,
            interceptors=self.interceptors + other.interceptors,
            lines=self.lines + other.lines,
        )

    @property
    def serves(self) -> bool:
        """Whether there is any workflow or activity to register."""
        return bool(
            self.workflows
            or self.activities
            or self.judging
            or any(self.assessing.values())
        )
