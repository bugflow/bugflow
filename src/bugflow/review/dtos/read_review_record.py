"""The request and response of ``ReadReviewRecordUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.review.domain.models.record import ReviewRecord
from bugflow.shared.domain.values.correlation import Correlation


class ReadReviewRecordRequest(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    # The workflow run of the evaluation to read.
    correlation: Correlation


class ReadReviewRecordResponse(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    record: ReviewRecord
    # The ids of exchanges that a judgement names and the store no
    # longer has.
    missing_exchanges: tuple[str, ...] = ()
