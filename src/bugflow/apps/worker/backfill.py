"""The workflow that evaluates a repository's closed pull requests.

A backfill fills the journal with evaluations of pull requests that
closed before the server was watching.

- An activity lists one page of closed pull requests, oldest first,
  without those already done.
- Each of the rest is evaluated by a child workflow that publishes
  nothing and, unless asked, judges nothing.
- The child's id is made from the pull request and its last commit. An
  id used by an evaluation that did not fail is not used again. So a
  backfill that is run twice evaluates each pull request once, and a
  failed evaluation is tried again.
- Evaluations run one at a time with a pause between them, so that the
  forge's rate limit is used slowly.
- After each page the workflow continues as a new run with the next
  page and its counts, so its history stays small.
- A query reports the counts so far.
"""

from datetime import timedelta

from pydantic import BaseModel, ConfigDict
from temporalio import workflow
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import (
    ChildWorkflowError,
    WorkflowAlreadyStartedError,
)

with workflow.unsafe.imports_passed_through():
    from bugflow.apps.worker.evaluate_pull_request import (
        evaluation_id_for,
    )
    from bugflow.review.dtos.evaluate_pull_request import (
        EvaluatePullRequestRequest,
    )
    from bugflow.work.dtos.list_backfill_page import (
        BackfillPullRequest,
        ListBackfillPageRequest,
        ListBackfillPageResponse,
    )

#: The activity that lists a page, and the one that says whether the
#: repository has any allowance left to spend.
LIST_BACKFILL_PAGE_ACTIVITY = "list_backfill_page"
OUT_OF_ROOM_ACTIVITY = "backfill_out_of_room"

#: The id of a change: before each evaluation the workflow asks whether
#: any allowance is left. A run from before the change replays without
#: asking.
ASK_WHAT_IS_LEFT = "backfill-asks-what-is-left"
#: The name of the child workflow that runs one evaluation.
EVALUATE_WORKFLOW = "EvaluatePullRequestWorkflow"
#: The name of the query that reports progress.
PROGRESS_QUERY = "progress"
#: The pause between evaluations.
INTERVAL = timedelta(seconds=3)


def _key(input: "BackfillInput", pull: BackfillPullRequest) -> str:
    """The part of a child workflow's id that tells a backfill's
    evaluation of this commit from any other. A backfill that judges and
    one that does not have different keys.
    """
    judged = "-judged" if input.use_judge else ""
    return f"backfill{judged}-{pull.head_sha}"


def backfill_id_for(repository: str) -> str:
    """The id of a repository's backfill workflow."""
    return f"backfill/{repository}"


class BackfillInput(BaseModel):
    """What a run is started with: the repository, written ``owner/repo``
    or ``forgejo:owner/repo``; the page to list; and the counts from
    earlier runs.
    """

    model_config = ConfigDict(frozen=True)

    repository: str
    use_judge: bool = False
    interval_seconds: float = INTERVAL.total_seconds()
    page: int = 1
    evaluated: int = 0
    already_evaluated: int = 0
    failed: int = 0


class BackfillProgress(BaseModel):
    """The counts so far.

    ``already_evaluated`` counts pull requests left out because they
    were already done. ``stopped`` gives the reason if the backfill
    stopped early because no allowance was left. It is empty otherwise.
    """

    model_config = ConfigDict(frozen=True)

    repository: str
    page: int
    evaluated: int
    already_evaluated: int
    failed: int
    done: bool = False
    stopped: str = ""


@workflow.defn(name="BackfillWorkflow")
class BackfillWorkflow:
    def __init__(self) -> None:
        self._progress: BackfillProgress | None = None

    @workflow.query(name=PROGRESS_QUERY)
    def progress(self) -> BackfillProgress | None:
        """The counts so far, or None before the run has started."""
        return self._progress

    def _update(self, **changes: object) -> BackfillProgress:
        """Change some of the counts and return them all."""
        assert self._progress is not None
        self._progress = self._progress.model_copy(update=changes)
        return self._progress

    @workflow.run
    async def run(self, input: BackfillInput) -> BackfillProgress:
        self._progress = BackfillProgress(
            repository=input.repository,
            page=input.page,
            evaluated=input.evaluated,
            already_evaluated=input.already_evaluated,
            failed=input.failed,
        )
        listed = await workflow.execute_activity(
            LIST_BACKFILL_PAGE_ACTIVITY,
            ListBackfillPageRequest(
                repository=input.repository,
                page=input.page,
                use_judge=input.use_judge,
            ),
            result_type=ListBackfillPageResponse,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(
                initial_interval=timedelta(seconds=5),
                backoff_coefficient=2.0,
                maximum_interval=timedelta(minutes=10),
                maximum_attempts=10,
            ),
        )
        progress = self._update(
            already_evaluated=self._progress.already_evaluated
            + listed.already_observed
        )
        for pull in listed.pulls:
            if workflow.patched(ASK_WHAT_IS_LEFT):
                refused: str = await workflow.execute_activity(
                    OUT_OF_ROOM_ACTIVITY,
                    input.repository,
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
                if refused:
                    workflow.logger.info("backfill stopped: %s", refused)
                    return self._update(stopped=refused)
            try:
                await workflow.execute_child_workflow(
                    EVALUATE_WORKFLOW,
                    EvaluatePullRequestRequest(
                        ref=pull.ref, use_judge=input.use_judge, publish=False
                    ),
                    id=evaluation_id_for(pull.ref, _key(input, pull)),
                    id_reuse_policy=(
                        WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
                    ),
                    execution_timeout=timedelta(minutes=30),
                )
                progress = self._update(evaluated=progress.evaluated + 1)
            except WorkflowAlreadyStartedError:
                progress = self._update(
                    already_evaluated=progress.already_evaluated + 1
                )
                continue
            except ChildWorkflowError as exc:
                workflow.logger.warning(
                    "backfill evaluation of %s failed: %s",
                    pull.ref,
                    exc.cause or exc,
                )
                progress = self._update(failed=progress.failed + 1)
            if input.interval_seconds > 0:
                await workflow.sleep(timedelta(seconds=input.interval_seconds))
        if listed.last:
            return self._update(done=True)
        workflow.continue_as_new(
            input.model_copy(
                update={
                    "page": input.page + 1,
                    "evaluated": progress.evaluated,
                    "already_evaluated": progress.already_evaluated,
                    "failed": progress.failed,
                }
            )
        )
