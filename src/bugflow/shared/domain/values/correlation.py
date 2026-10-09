"""Which run a fact was recorded in."""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Correlation:
    """The workflow execution a fact was recorded in."""

    workflow_id: str
    run_id: str
