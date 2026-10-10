"""Where one repository's period on one pace layer begins.

A cadence is a frequency and nothing more, and the method owns it. Where
a period starts is a fact about the people who read it, so it is the
repository's: one repository takes stock on first Tuesdays and another
on second Fridays, and both are fortnightly.

A clock cadence is bounded by a phase and an event cadence by the window
its signals settle in. Both say the same thing, when this repository's
period begins and ends, so both are one declaration rather than two.

The boundary is text this context does not read. Which layers exist is
the method's, as a spend scope's layer already is, and what a boundary
means depends on the cadence that layer rides, which is the method's
too. This context holds the statement, and the application is where
the two meet.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class LayerBoundary:
    """One repository's boundary on one pace layer."""

    forge: str
    repo: str
    #: A layer the topology declares.
    layer: str
    #: The phase, for a layer a clock fires, or the settling window for
    #: one an event fires. Never empty: silence about a boundary does
    #: not fail, it guesses, and a guessed boundary is invisible until
    #: the money is counted.
    boundary: str
