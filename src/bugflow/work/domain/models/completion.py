"""A completion: a runner's message that one of its runs has finished."""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Completion:
    """Says which run finished, and nothing about how it went.

    Each runner reports a finished run in its own way. This is the form
    they are all turned into. What the run produced is read from the
    runner afterwards, by collecting it.
    """

    #: The name of the runner that was given the work.
    runner: str
    #: The runner's own name for the work, as in the run's handle.
    remote_id: str
