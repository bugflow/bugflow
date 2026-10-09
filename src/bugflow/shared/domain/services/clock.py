"""The time a fact is recorded at."""

from datetime import datetime
from typing import Protocol


class ClockService(Protocol):
    def now(self) -> datetime: ...
