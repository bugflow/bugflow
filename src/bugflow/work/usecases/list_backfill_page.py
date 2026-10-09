"""List one page of the closed pull requests that a backfill should
review.

A backfill reviews a repository's old, closed pull requests. This use
case lists one page of them and leaves out the ones already done, so
that a backfill that is run again, or that carries on after being
stopped, does not review the same commit twice.

Which pull requests are already done depends on whether the backfill
has pull requests judged:

- A backfill without judging has nothing to do for a pull request if
  the journal says a snapshot was taken of it at its last commit.
- A backfill with judging has nothing to do only if, in the same
  workflow run that took that snapshot, a judge gave an answer. A run
  that took a snapshot without judging does not count. Nor does a run
  in which the judge was unavailable, so a backfill that was stopped
  when a quota ran out carries on from the pull requests that were not
  judged.
"""

from collections.abc import Mapping

from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.work.domain.facts import JUDGE_INVOKED, PR_OBSERVED
from bugflow.work.domain.models.backfill import WatchedRepository
from bugflow.work.domain.repositories.backfill import (
    ClosedPullRequestFeedRepository,
)
from bugflow.work.domain.services.journal import JournalService
from bugflow.work.dtos.list_backfill_page import (
    BackfillPullRequest,
    ListBackfillPageRequest,
    ListBackfillPageResponse,
)


class ListBackfillPageUseCase:
    def __init__(
        self,
        feeds: Mapping[str, ClosedPullRequestFeedRepository],
        journal: JournalService,
    ) -> None:
        """``feeds`` has one feed of closed pull requests for each kind
        of forge, keyed by "github" or "forgejo"."""
        self._feeds = feeds
        self._journal = journal

    def execute(
        self, request: ListBackfillPageRequest
    ) -> ListBackfillPageResponse:
        """Return the page.

        Raises ``ValueError`` if the repository's name cannot be read,
        or if there is no feed for its kind of forge. An error from the
        feed is passed on.
        """
        repository = WatchedRepository.parse(request.repository)
        feed = self._feeds.get(repository.forge)
        if feed is None:
            raise ValueError(f"no {repository.forge} forge configured")
        page = feed.closed_pull_requests(
            repository.owner, repository.repo, request.page
        )
        pulls: list[BackfillPullRequest] = []
        already = 0
        for pull in page.pulls:
            if self._done(pull.ref, pull.head_sha, request.use_judge):
                already += 1
                continue
            pulls.append(
                BackfillPullRequest(ref=pull.ref, head_sha=pull.head_sha)
            )
        return ListBackfillPageResponse(
            pulls=tuple(pulls), already_observed=already, last=page.last
        )

    def _done(
        self, ref: PullRequestRef, head_sha: str, use_judge: bool
    ) -> bool:
        """Whether the backfill has nothing to do for this commit of
        the pull request."""
        runs = {
            (entry.workflow_id, entry.run_id)
            for entry in self._journal.events_for_pull_request(
                ref, PR_OBSERVED
            )
            if entry.commit_sha == head_sha
        }
        if not runs or not use_judge:
            return bool(runs)
        return any(
            (entry.workflow_id, entry.run_id) in runs
            and str(entry.payload.get("status", "")).startswith("judged")
            for entry in self._journal.events_for_pull_request(
                ref, JUDGE_INVOKED
            )
        )
