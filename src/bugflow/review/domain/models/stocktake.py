"""The range of merged pull requests that one stocktake covers.

A stocktake runs on a schedule, for one layer. A layer is a named
period, such as a week or a quarter. A stocktake covers what merged
between the layer's last stocktake and now.

Each stocktake leaves a mark that says when it ran. The next one starts
from the mark, so nothing is covered twice. If nothing merged in the
range, no review is run and the stocktake costs nothing.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, kw_only=True)
class Merged:
    """One pull request that merged."""

    pull_request: int
    head_sha: str
    merged_at: datetime


@dataclass(frozen=True, kw_only=True)
class Mark:
    """When a layer last took stock of a repository, and the commit it
    got to."""

    taken_at: datetime
    #: The last commit that stocktake covered. The next stocktake
    #: compares against it, so that it reads only what changed since.
    #: None if that range was empty, or if the mark is an old one that
    #: recorded no commit.
    head_sha: str | None = None


@dataclass(frozen=True, kw_only=True)
class Range:
    """What one stocktake covers: a period, and what merged in it."""

    #: The start of the period. None on a layer's first stocktake, which
    #: covers everything the journal has.
    since: datetime | None
    until: datetime
    #: The pull requests that merged in the period, oldest first.
    merged: tuple[Merged, ...]
    #: The two commits a review of the range compares: where the last
    #: stocktake got to, and the last pull request merged since. The
    #: base is None on a layer's first stocktake. The head is None if
    #: nothing merged.
    base_sha: str | None = None
    head_sha: str | None = None

    @property
    def worth_taking(self) -> bool:
        """Whether anything merged in the range."""
        return bool(self.merged)


def stocktake_range(
    *, now: datetime, mark: Mark | None, merged: Iterable[Merged]
) -> Range:
    """Work out the range from the layer's last mark to ``now``.

    A pull request that merged exactly at the mark belongs to the
    stocktake that left the mark. One that merged exactly at ``now``
    belongs to this one.
    """
    inside = tuple(
        sorted(
            (
                one
                for one in merged
                if (mark is None or one.merged_at > mark.taken_at)
                and one.merged_at <= now
            ),
            key=lambda one: (one.merged_at, one.pull_request),
        )
    )
    return Range(
        since=mark.taken_at if mark else None,
        until=now,
        merged=inside,
        base_sha=mark.head_sha if mark else None,
        head_sha=inside[-1].head_sha if inside else None,
    )
