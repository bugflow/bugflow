"""Tests of ``ReproduceJudgementUseCase``: a stored judgement is run
again and both results are returned."""

import pytest

from bugflow.review.domain.errors import ExchangeNotFoundError
from bugflow.review.domain.models.judgement import (
    JudgeExchange,
    JudgeReproduction,
)
from bugflow.review.dtos.reproduce_judgement import ReproduceJudgementRequest
from bugflow.review.infrastructure.in_memory_judge_archive import (
    InMemoryJudgeArchive,
)
from bugflow.review.usecases.reproduce_judgement import (
    ReproduceJudgementUseCase,
)

STORED = JudgeExchange(
    request={"policy": "P-01"},
    response={"violations": [{"clause": "RULE-1", "quote": "and also"}]},
)


class SecondAnswer:
    """Answers a stored request again, with the violations it is given."""

    def __init__(self, violations: tuple[str, ...]) -> None:
        self.violations = violations

    def reproduce(self, exchange: JudgeExchange) -> JudgeReproduction:
        return JudgeReproduction(
            exchange_id=exchange.exchange_id,
            model="a-model",
            archived=("RULE-1: and also",),
            replayed=self.violations,
            replay=JudgeExchange(
                request=exchange.request,
                response={"violations": list(self.violations)},
            ),
        )


def test_the_same_answer_twice_matches() -> None:
    archive = InMemoryJudgeArchive()
    exchange_id = archive.put(STORED)

    response = ReproduceJudgementUseCase(
        archive, SecondAnswer(("RULE-1: and also",))
    ).execute(ReproduceJudgementRequest(exchange_id=exchange_id))

    assert response.reproduction.matches
    assert response.reproduction.exchange_id == exchange_id


def test_a_different_answer_does_not_match_and_is_stored_too() -> None:
    archive = InMemoryJudgeArchive()
    exchange_id = archive.put(STORED)

    response = ReproduceJudgementUseCase(archive, SecondAnswer(())).execute(
        ReproduceJudgementRequest(exchange_id=exchange_id)
    )

    assert not response.reproduction.matches
    assert len(archive.exchanges) == 2
    assert response.reproduction.replay.exchange_id in archive.exchanges


def test_an_exchange_that_is_not_stored_is_an_error() -> None:
    use_case = ReproduceJudgementUseCase(
        InMemoryJudgeArchive(), SecondAnswer(())
    )

    with pytest.raises(ExchangeNotFoundError):
        use_case.execute(ReproduceJudgementRequest(exchange_id="missing"))
