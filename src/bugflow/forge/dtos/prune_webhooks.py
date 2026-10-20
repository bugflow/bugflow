"""The request and response of ``PruneWebhooksUseCase``."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from bugflow.forge.domain.values.watched_repository import WatchedRepository

PruneOutcome = Literal["deleted", "would delete", "absent", "failed"]


class PrunedRepository(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: WatchedRepository
    outcome: PruneOutcome
    hook_ids: tuple[int, ...] = ()
    detail: str = ""


class PruneWebhooksRequest(BaseModel):
    """``url`` is the address whose webhooks are deleted. ``keep`` is
    the address this server answers on now, which no prune may name.
    With ``dry_run`` the webhooks are listed and nothing is deleted."""

    model_config = ConfigDict(frozen=True)

    repositories: tuple[WatchedRepository, ...]
    url: str
    keep: str
    dry_run: bool = False


class PruneWebhooksResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcomes: tuple[PrunedRepository, ...]

    @property
    def failed(self) -> tuple[PrunedRepository, ...]:
        return tuple(o for o in self.outcomes if o.outcome == "failed")
