"""The interface for storing the judge's exchanges with its model.

A judgement can be run again only if the request the model was sent and
the response it gave are kept, and not just the verdict.
"""

from typing import Protocol

from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.shared.domain.repositories.base import BaseRepository


class JudgeArchiveRepository(BaseRepository[JudgeExchange], Protocol):
    def put(self, exchange: JudgeExchange) -> str:
        """Store an exchange and return its id. Storing the same
        exchange again stores nothing new and returns the same id."""
        ...

    def get(self, exchange_id: str) -> JudgeExchange:
        """Return the exchange. Raises ``ExchangeNotFoundError`` if
        there is none under the id."""
        ...
