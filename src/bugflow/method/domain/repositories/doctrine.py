"""The interface that reads the doctrine a judge cites."""

from typing import Protocol

from bugflow.method.domain.models.doctrine import Doctrine
from bugflow.shared.domain.repositories.base import BaseRepository


class DoctrineRepository(BaseRepository[Doctrine], Protocol):
    def load(self) -> Doctrine: ...
