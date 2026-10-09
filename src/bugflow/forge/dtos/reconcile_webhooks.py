"""The request and response of ``ReconcileWebhooksUseCase``."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from bugflow.forge.domain.values.watched_repository import WatchedRepository
from bugflow.shared.domain.values.correlation import Correlation

#: The events a webhook must send. ``pull_request`` is what starts an
#: evaluation. ``issue_comment`` is how a ``/dismiss`` comment arrives.
EVENTS = frozenset({"pull_request", "issue_comment"})

Outcome = Literal[
    "created", "updated", "unchanged", "removed", "renamed", "failed"
]


class RepositoryOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: WatchedRepository
    outcome: Outcome
    detail: str = ""


class ReconcileWebhooksRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    repositories: tuple[WatchedRepository, ...]
    url: str
    secret: str
    correlation: Correlation
    events: frozenset[str] = EVENTS


class ReconcileWebhooksResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcomes: tuple[RepositoryOutcome, ...]

    @property
    def failed(self) -> tuple[RepositoryOutcome, ...]:
        return tuple(o for o in self.outcomes if o.outcome == "failed")
