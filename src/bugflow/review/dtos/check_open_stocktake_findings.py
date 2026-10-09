"""The request and response of ``CheckOpenStocktakeFindingsUseCase``."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CheckOpenStocktakeFindingsRequest(BaseModel):
    """The check takes no input. It reads every stocktake's findings."""

    model_config = ConfigDict(frozen=True)


class OpenStocktakeFinding(BaseModel):
    """One finding that is still open."""

    model_config = ConfigDict(frozen=True)

    # The id of the journal entry that recorded the finding.
    event_id: str
    forge: str
    repo: str
    layer: str
    agent_id: str
    head_sha: str | None
    found_at: datetime
    where: str
    quote: str
    claim: str
    kind: str = ""


class CheckOpenStocktakeFindingsResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    # Every open finding, oldest first.
    open_findings: tuple[OpenStocktakeFinding, ...] = ()
