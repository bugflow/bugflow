"""The request and response of ``TakeStockUseCase``."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.correlation import Correlation


class TakeStockRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    forge: str
    # The repository as the journal names it: "owner/name".
    repo: str
    # The name of the layer that is taking stock.
    layer: str
    correlation: Correlation


class TakeStockResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    # The start of the range. None on a layer's first stocktake, which
    # covers everything.
    since: datetime | None
    until: datetime
    # How many pull requests merged in the range.
    merged: int
    # Whether the range is worth a review: whether anything merged.
    worth_taking: bool
    # The two commits a review of the range compares. The base is None
    # on a layer's first stocktake. The head is None if nothing merged.
    base_sha: str | None = None
    head_sha: str | None = None
