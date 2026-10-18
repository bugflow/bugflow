"""A store of judge exchanges that keeps them in a dictionary, for
tests and for running an evaluation with no database."""

import json

from bugflow.review.domain.errors import ExchangeNotFoundError
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.shared.domain.errors import ContentTooLargeError


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

    def get_bounded(
        self, exchange_id: str, max_bytes: int
    ) -> tuple[JudgeExchange, int]:
        exchange = self.get(exchange_id)
        size = 1024 + sum(
            len(json.dumps(part, ensure_ascii=False).encode("utf-8"))
            for part in (exchange.request, exchange.response)
        )
        if size > max_bytes:
            raise ContentTooLargeError("exchange exceeds the byte allowance")
        return exchange, size
