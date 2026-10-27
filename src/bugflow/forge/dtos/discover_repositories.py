"""The request and response of ``DiscoverRepositoriesUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.forge.domain.models.forge_repository import RepositoryChange
from bugflow.shared.domain.values.correlation import Correlation


class DiscoverRepositoriesRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    forge: str = "github"
    #: The owners whose repositories are listed.
    owners: tuple[str, ...]
    correlation: Correlation


class DiscoverRepositoriesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    changes: tuple[RepositoryChange, ...]
    #: An owner that could not be listed, with why.
    failures: tuple[str, ...] = ()
