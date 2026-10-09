"""The interface for reading the evaluation regime in force."""

from typing import Protocol

from bugflow.forge.domain.values.evaluation_regime import EvaluationRegime
from bugflow.shared.domain.repositories.base import BaseRepository


class EvaluationRegimeRepository(BaseRepository[EvaluationRegime], Protocol):
    def current(self) -> EvaluationRegime:
        """The rules in force now."""
        ...
