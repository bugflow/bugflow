"""A store of judge exchanges that keeps them in a dictionary, for
tests and for running an evaluation with no database."""

from bugflow.review.domain.errors import ExchangeNotFoundError
from bugflow.review.domain.models.judgement import JudgeExchange


class InMemoryJudgeArchive:
    def __init__(self) -> None:
        self.exchanges: dict[str, JudgeExchange] = {}

    def put(self, exchange: JudgeExchange) -> str:
        self.exchanges.setdefault(exchange.exchange_id, exchange)
        return exchange.exchange_id

    def get(self, exchange_id: str) -> JudgeExchange:
        try:
            return self.exchanges[exchange_id]
        except KeyError as exc:
            raise ExchangeNotFoundError(
                f"no archived exchange {exchange_id}"
            ) from exc
