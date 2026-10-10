"""The interface for reading the corpus an evaluation runs under."""

from typing import Protocol

from bugflow.method.domain.models.corpus import Corpus
from bugflow.shared.domain.repositories.base import BaseRepository


class CorpusRepository(BaseRepository[Corpus], Protocol):
    def load(self) -> Corpus:
        """The corpus in force now."""
        ...
