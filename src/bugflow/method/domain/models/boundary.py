"""What a declared boundary says, read against the cadence it bounds.

A repository declares where a period begins, per layer, and this server
declares its own per cadence; the text declared means nothing without
the cadence, because a time of day bounds a nightly period and a weekday
bounds a weekly one. Reading it is therefore the method's, beside the
cadences it is read against.

Four shapes, and the last of them bounds any cadence:

===================  ==========================================
``23:30``            a time of day
``SUN 23:30``        a day of the week and a time
``1 23:30``          a day of the month and a time
``2026-09-01 09:00`` an instant, from which periods are counted
===================  ==========================================

A fortnight, a quarter and a year can only be said the fourth way: every
second Friday is not a weekday, it is a weekday and a starting point.

A cadence no clock fires is bounded by the window its signals settle in,
written as seconds: ``60s``. Five pushes inside it are one event and one
run.
"""

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

#: Weekday names, as a declaration writes them, in the order
#: ``datetime.weekday`` counts.
DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

_TIME = r"(?P<hour>\d{1,2}):(?P<minute>\d{2})"
_AT = re.compile(rf"\A{_TIME}\Z")
_WEEKDAY = re.compile(rf"\A(?P<day>[A-Z]{{3}})\s+{_TIME}\Z")
_MONTH_DAY = re.compile(rf"\A(?P<day>\d{{1,2}})\s+{_TIME}\Z")
_INSTANT = re.compile(rf"\A(?P<date>\d{{4}}-\d{{2}}-\d{{2}})\s+{_TIME}\Z")
_SETTLES = re.compile(r"\A(?P<seconds>\d+)s\Z")


class BoundaryError(ValueError):
    """The boundary declared was not one this cadence can be bounded by."""


@dataclass(frozen=True, kw_only=True)
class SettlingWindow:
    """How long a burst of signals has to be quiet to be one event."""

    seconds: int


@dataclass(frozen=True, kw_only=True)
class Phase:
    """Where a clock cadence's periods begin.

    One instant, from which every period of that cadence is counted. A
    declaration that names only a time or a weekday says where periods
    begin without saying which one is first; this resolves it against a
    date near the reading, because a day that repeats needs no epoch
    and a fortnight that does not is written as an instant.
    """

    at: datetime


def settling_window(boundary: str) -> SettlingWindow:
    """The window a cadence no clock fires is bounded by."""
    found = _SETTLES.match(boundary.strip())
    if not found:
        raise BoundaryError(
            f"{boundary!r} is not a settling window; write one as seconds, "
            f"such as 60s"
        )
    return SettlingWindow(seconds=int(found.group("seconds")))


def _clock(found: re.Match[str]) -> time:
    hour, minute = int(found.group("hour")), int(found.group("minute"))
    if hour > 23 or minute > 59:
        raise BoundaryError(f"{hour:02d}:{minute:02d} is not a time of day")
    return time(hour=hour, minute=minute)


def phase(boundary: str, span: str, near: datetime, zone: str) -> Phase:
    """Where periods of that span begin, as an instant near the reading.

    ``near`` is the moment being asked about, and is what a repeating
    declaration is resolved against: the Monday of its week, the first
    of its month. An instant declaration ignores it, which is what makes
    a fortnight countable.
    """
    text = boundary.strip()
    here = near.astimezone(ZoneInfo(zone))

    if found := _INSTANT.match(text):
        naive = datetime.combine(
            datetime.strptime(found.group("date"), "%Y-%m-%d").date(),
            _clock(found),
        )
        return Phase(at=naive.replace(tzinfo=ZoneInfo(zone)))

    if span in ("fortnight", "quarter", "year"):
        raise BoundaryError(
            f"a {span} begins at an instant, not at {text!r}: write it as a "
            f"date and a time, such as 2026-09-01 09:00, because every "
            f"second one of these is not a day of any week or month"
        )

    if found := _AT.match(text):
        return Phase(
            at=here.replace(
                hour=_clock(found).hour,
                minute=_clock(found).minute,
                second=0,
                microsecond=0,
            )
        )

    if found := _WEEKDAY.match(text):
        day = found.group("day").upper()
        if day not in DAYS:
            raise BoundaryError(
                f"{day!r} is not a day; name one of {', '.join(DAYS)}"
            )
        midnight = here.replace(hour=0, minute=0, second=0, microsecond=0)
        monday = midnight - timedelta(days=midnight.weekday())
        return Phase(
            at=(monday + timedelta(days=DAYS.index(day))).replace(
                hour=_clock(found).hour, minute=_clock(found).minute
            )
        )

    if found := _MONTH_DAY.match(text):
        day = int(found.group("day"))
        if not 1 <= day <= 28:
            raise BoundaryError(
                f"{day} is no day of every month; name one from 1 to 28, so "
                f"that every month has one"
            )
        return Phase(
            at=here.replace(
                day=day,
                hour=_clock(found).hour,
                minute=_clock(found).minute,
                second=0,
                microsecond=0,
            )
        )

    raise BoundaryError(
        f"{text!r} is no boundary; write a time, a day and a time, a day "
        f"of the month and a time, or a date and a time"
    )
