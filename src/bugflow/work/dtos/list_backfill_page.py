"""The request and response of ``ListBackfillPageUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class ListBackfillPageRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    # ``owner/repo`` for a repository on GitHub, or ``forgejo:owner/repo``.
    repository: str
    # Pages are counted from 1.
    page: int = 1
    # True if the backfill will have each pull request judged. This
    # changes which pull requests count as already done.
    use_judge: bool = False


class BackfillPullRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref: PullRequestRef
    head_sha: str


class ListBackfillPageResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    # The pull requests on the page that the backfill should review.
    pulls: tuple[BackfillPullRequest, ...]
    # How many pull requests on the page were left out as already done.
    already_observed: int
    # True if this is the repository's last page.
    last: bool
