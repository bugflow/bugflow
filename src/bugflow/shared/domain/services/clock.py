"""The interface for reading the current time.

Code asks this instead of the system clock, so that a test can set the
time.
"""

from datetime import datetime
from typing import Protocol


class ClockService(Protocol):
    def now(self) -> datetime:
        """The current time, with a time zone."""
        ...
