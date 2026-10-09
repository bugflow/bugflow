"""The review scope: which policies a pull request was reviewed against."""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class ReviewScope:
    """Two lists of policy ids.

    ``held`` is every policy the server could apply. ``reviewed_for`` is
    the ones this repository asked for, which are the ones actually
    applied.

    Both are recorded because the difference matters when counting how
    often a policy finds something: a policy that was switched off for a
    repository must not be counted as one that ran and found nothing.
    """

    held: tuple[str, ...] = ()
    reviewed_for: tuple[str, ...] = ()
