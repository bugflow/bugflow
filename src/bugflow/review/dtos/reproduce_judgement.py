"""The request and response of ``ReproduceJudgementUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.judgement import JudgeReproduction


class ReproduceJudgementRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    # The id of the stored exchange to run again.
    exchange_id: str


class ReproduceJudgementResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reproduction: JudgeReproduction
