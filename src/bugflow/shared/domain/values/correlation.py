"""Correlation: which workflow run something happened in."""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Correlation:
    """Identifies one run of one workflow. Recorded with each fact so that the
    facts of a run can be found together.
    """

    workflow_id: str
    run_id: str
