"""Run a stored judgement again and compare the results.

A judged finding gives the id of the exchange it came from. This use
case sends that exchange's request to the model again and returns what
the model found then beside what it finds now. The new exchange is
stored too.
"""

from bugflow.review.domain.repositories.judge_archive import (
    JudgeArchiveRepository,
)
from bugflow.review.domain.services.judge import JudgeReproducerService
from bugflow.review.dtos.reproduce_judgement import (
    ReproduceJudgementRequest,
    ReproduceJudgementResponse,
)


class ReproduceJudgementUseCase:
    def __init__(
        self, archive: JudgeArchiveRepository, judge: JudgeReproducerService
    ) -> None:
        self._archive = archive
        self._judge = judge

    def execute(
        self, request: ReproduceJudgementRequest
    ) -> ReproduceJudgementResponse:
        """Raises ``ExchangeNotFoundError`` if no exchange is stored
        under the id, and ``JudgeUnavailableError`` if the model cannot
        be asked."""
        archived = self._archive.get(request.exchange_id)
        reproduction = self._judge.reproduce(archived)
        self._archive.put(reproduction.replay)
        return ReproduceJudgementResponse(reproduction=reproduction)
