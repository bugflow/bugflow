"""Where this server's periods begin, for allowances no repository owns.

A boundary belongs to the repository whose period it bounds, and the
schedules that fire for it read that one. An allowance may be scoped
more widely than any repository, a weekly ceiling over everything is
one row covering every repository there is, and then there is no
repository whose decision to read.

So the server declares its own, per cadence. Declared and not
defaulted: a boundary nobody stated is not filled in by the code. It is
stated, listed beside the rest, and absent until somebody writes it.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class CadenceBoundary:
    """Where this server's periods of one cadence begin."""

    #: A cadence the topology declares.
    cadence: str
    #: Where its periods begin, read against that cadence.
    boundary: str
