"""The topology of feedback loops: which processes a pace layer holds,
and at what cadence.

A pace layer is not a property of a repository. It holds processes: the
pull request and its callbacks are one layer, and a nightly, weekly,
fortnightly, monthly, quarterly or annual reading is another. Nothing
here names a repository, because a run works its subject out when it
runs, from what the repositories declare.

A cadence nobody defined, a process nobody declared, and a layer holding
no process are each refused where the topology is read, which is when
the worker starts rather than at the first run.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, get_args

from bugflow.shared.domain.values.budget import Budget

#: What a process reads. A pull request's is keyed on a head commit, so
#: a later push supersedes it; a range's is keyed on two points in time,
#: and a reading of a month's work does not stop being true because
#: somebody pushed this morning.
Subject = Literal["pull request", "range"]

SUBJECTS: tuple[Subject, ...] = get_args(Subject)


#: How long one period of a cadence lasts, as the calendar counts it. A
#: property of the cadence and not a second list beside it: an allowance
#: is per cadence, and what it is counted over has to come from the
#: cadence itself or the two drift.
Span = Literal["", "day", "week", "fortnight", "month", "quarter", "year"]


@dataclass(frozen=True, kw_only=True)
class Cadence:
    """How often a layer's processes run, and how long one period is."""

    name: str
    #: Whether a clock fires the layer. A cadence no clock fires is fired
    #: by an event, and a layer on one gets no schedule.
    on_a_clock: bool
    #: The calendar span of one period. Empty for a cadence no clock
    #: fires: one event is its period, and an event has no length.
    span: Span = ""


#: The cadence no clock fires. Its period is one event, which is what a
#: burst of deliveries settling amounts to rather than each delivery.
EVENT = Cadence(name="event", on_a_clock=False)
NIGHTLY = Cadence(name="nightly", on_a_clock=True, span="day")
WEEKLY = Cadence(name="weekly", on_a_clock=True, span="week")
FORTNIGHTLY = Cadence(name="fortnightly", on_a_clock=True, span="fortnight")
MONTHLY = Cadence(name="monthly", on_a_clock=True, span="month")
QUARTERLY = Cadence(name="quarterly", on_a_clock=True, span="quarter")
ANNUAL = Cadence(name="annual", on_a_clock=True, span="year")

CADENCES: Mapping[str, Cadence] = {
    cadence.name: cadence
    for cadence in (
        EVENT,
        NIGHTLY,
        WEEKLY,
        FORTNIGHTLY,
        MONTHLY,
        QUARTERLY,
        ANNUAL,
    )
}


@dataclass(frozen=True, kw_only=True)
class Process:
    """One feedback loop a layer holds, and what it reads."""

    name: str
    subject: Subject
    #: The reviewer this process runs, where it is a review. None for a
    #: process that is not one, such as the evaluation a delivery starts
    #: or the conversation read at a close. A reviewer no layer names
    #: runs nowhere, which is how a reviewer is moved from one cadence
    #: to another without touching a repository's declarations.
    reviewer: str | None = None
    #: What this work is worth: a range review reads a week and is worth
    #: more than a review of one pull request. It is the method's, so it
    #: changes by a commit and a deploy, where what a repository may
    #: spend changes by a row. None where nothing said.
    worth: Budget | None = None
    #: Whether the judge reads this process's subject. The judge is not
    #: dispatched at a worktree the way a reviewer is, so no reviewer
    #: names it, and a process holding no reviewer is not a process
    #: holding no review. Which policies are judged is the repository's
    #: declaration rather than the topology's, so nothing here lists
    #: them: a layer would drift from the rows that decide what runs.
    judges: bool = False


@dataclass(frozen=True, kw_only=True)
class PaceLayer:
    """A layer: a cadence, and the processes that run at it.

    Its identity is its name. Where it was declared, and beside what,
    says nothing about it.
    """

    name: str
    cadence: Cadence
    #: In name order, so that two declarations of the same processes
    #: are the same layer.
    processes: tuple[Process, ...]


def cadence(name: str) -> Cadence:
    """The cadence of that name, or a ValueError naming those defined."""
    found = CADENCES.get(name)
    if found is None:
        raise ValueError(
            f"{name!r} is not a cadence; defined: {', '.join(CADENCES)}"
        )
    return found


def process(
    name: str,
    subject: str,
    reviewer: str | None = None,
    worth: Budget | None = None,
    judges: bool = False,
) -> Process:
    """A process reading that subject, or a ValueError naming those
    defined."""
    if subject not in SUBJECTS:
        raise ValueError(
            f"{name}: {subject!r} is not a subject; "
            f"defined: {', '.join(SUBJECTS)}"
        )
    return Process(
        name=name,
        subject=subject,
        reviewer=reviewer,
        worth=worth,
        judges=judges,
    )


def layer(
    name: str,
    cadence_name: str,
    process_names: Iterable[str],
    declared: Mapping[str, Process],
) -> PaceLayer:
    """A layer of that name, holding the declared processes it names.

    A process it names that nobody declared, and a layer holding none,
    are both a ValueError: a schedule that fires and runs nothing costs
    what a run costs and reports nothing.
    """
    held = sorted(set(process_names))
    if not held:
        raise ValueError(f"the layer {name!r} holds no process")
    unknown = [one for one in held if one not in declared]
    if unknown:
        raise ValueError(
            f"the layer {name!r} holds {', '.join(unknown)}, "
            f"which no process declares; declared: {', '.join(declared)}"
        )
    return PaceLayer(
        name=name,
        cadence=cadence(cadence_name),
        processes=tuple(declared[one] for one in held),
    )
