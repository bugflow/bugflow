"""A test that a worker built from this package's parts reviews a pull
request from its first delivery to its close.

The worker is the real one: ``run`` over the parts
``review.parts_from_environment`` builds, so the three kinds of queue,
the four workflows and every activity are what a deployed worker has.
The deployment is put in force in a database made for the test, and
the journal, the snapshots and the review records are that database's.
Temporal is its time-skipping test server.

Two things are stood in for, because they are other people's servers:
the forge, which answers with one pull request and keeps what is
written to it, and the judge, which finds one thing.

Skipped unless DATABASE_URL names a Postgres server.
"""

import asyncio
import uuid
from datetime import timedelta

import sqlalchemy as sa
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment

from bugflow.apps.ingress.ingress import worker_workflows
from bugflow.apps.shared.journals import review_journal
from bugflow.apps.worker import review
from bugflow.apps.worker.pull_request import DEBOUNCE
from bugflow.apps.worker.tests.deployed import (
    REPOSITORY,
    WIDGETS,
    put_in_force,
)
from bugflow.apps.worker.worker import run
from bugflow.forge.domain.facts import PR_OBSERVED
from bugflow.forge.domain.models.pull_request import (
    CommitSnapshot,
    PullRequestSnapshot,
)
from bugflow.forge.domain.services.forge import CommitState
from bugflow.forge.domain.values.conversation import PullRequestState, Reaction
from bugflow.review.domain.facts import (
    ACTION_TAKEN,
    FINDING_RAISED,
    JUDGE_INVOKED,
    POLICY_CHECKED,
)
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.enforcement import ADVISE
from bugflow.review.domain.models.finding import Finding
from bugflow.review.domain.models.judge_assessment import JudgeAssessment
from bugflow.review.domain.models.judgement import JudgeExchange
from bugflow.review.domain.models.submission import Submission
from bugflow.review.infrastructure.sqlalchemy_enforcement import (
    SqlAlchemyEnforcement,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef
from bugflow.shared.infrastructure.database import engine_url
from bugflow.shared.infrastructure.sqlalchemy_journal import journal

REF = PullRequestRef(owner="example-org", repo="widgets", number=7)
HEAD = "a" * 40
FOUND = "The description does not say what changed."


class OnePullRequest:
    """A forge with one open pull request, which keeps what is written
    to it."""

    def __init__(self) -> None:
        self.comments: dict[int, str] = {}
        self.labels: set[str] = set()
        self.statuses: dict[str, tuple[str, str]] = {}

    def fetch_snapshot(self, ref: PullRequestRef) -> PullRequestSnapshot:
        return PullRequestSnapshot(
            ref=ref,
            title="Add a thing",
            body="Things were changed.",
            head_branch="a-thing",
            base_branch="master",
            commits=(CommitSnapshot(sha=HEAD, message="Add a thing"),),
            files=(),
        )

    def is_open(self, ref: PullRequestRef) -> bool:
        return True

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        for comment_id, existing in self.comments.items():
            if marker in existing:
                self.comments[comment_id] = body
                return comment_id
        self.comments[len(self.comments) + 1] = body
        return len(self.comments)

    def set_labels(
        self,
        ref: PullRequestRef,
        add: frozenset[str],
        remove: frozenset[str],
    ) -> None:
        self.labels = (self.labels - remove) | add

    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: CommitState,
        description: str,
    ) -> None:
        self.statuses[context] = (state, description)

    def reactions(
        self, ref: PullRequestRef, comment_id: int
    ) -> tuple[Reaction, ...]:
        return (Reaction(content="+1", login="a-reader"),)

    def state(self, ref: PullRequestRef) -> PullRequestState:
        return PullRequestState(merged=False, head_sha=HEAD)


class FindsOneThing:
    """A judge of the deployment's one judged policy, which raises one
    warning whatever it reads."""

    model_id = "a-model"
    fingerprint = "finds-one-thing"
    policies = ("P-01",)

    def __init__(self) -> None:
        self.asked: list[str] = []

    def assess(
        self, submission: Submission, doctrine: DoctrineText, policy_id: str
    ) -> JudgeAssessment:
        self.asked.append(policy_id)
        return JudgeAssessment(
            findings=(
                Finding(
                    policy_id=policy_id,
                    severity="warn",
                    clause="EX-1",
                    subject="pull request",
                    message=FOUND,
                    judged_by="a-model",
                ),
            ),
            model="a-model",
            exchange=JudgeExchange(
                request={"policy": policy_id}, response={"ok": True}
            ),
        )


async def until(happened: object, what: str) -> None:
    """Wait, in real time, for the worker to get somewhere."""
    for _ in range(600):
        if happened():  # type: ignore[operator]
            return
        await asyncio.sleep(0.05)
    raise AssertionError(f"the worker never {what}")


def test_a_pull_request_is_reviewed_and_a_finding_published(
    database_url: str,
) -> None:
    put_in_force(database_url)
    SqlAlchemyEnforcement(database_url).bind(*WIDGETS, ADVISE)
    forge, judge = OnePullRequest(), FindsOneThing()
    workflows = worker_workflows()

    async def scenario() -> None:
        async with await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter
        ) as env:
            environ = {
                "DATABASE_URL": database_url,
                "BUILD_SHA": "b" * 40,
                "TEMPORAL_ADDRESS": (
                    env.client.service_client.config.target_host
                ),
                "TEMPORAL_NAMESPACE": env.client.namespace,
                "TEMPORAL_TASK_QUEUE": f"test-{uuid.uuid4()}",
            }
            parts = review.parts_from_environment(
                environ, forge=forge, judge=judge
            )
            stop = asyncio.Event()
            serving = asyncio.create_task(run(environ, parts, stop))
            try:
                # A delivery, handed over as the ingress hands one over.
                handle = await env.client.start_workflow(
                    workflows.pull_request,
                    workflows.input_for(REF, None),
                    id=workflows.workflow_id_for(REF),
                    task_queue=environ["TEMPORAL_TASK_QUEUE"],
                    start_signal=workflows.delivery_signal,
                    start_signal_args=["d-1"],
                )
                await env.sleep(DEBOUNCE + timedelta(seconds=1))
                await until(lambda: forge.comments, "published a comment")
                await until(lambda: forge.labels, "set a label")
                # The pull request closes, and the workflow ends.
                await handle.signal(workflows.close_signal, "d-close")
                await asyncio.wait_for(handle.result(), 60)
            finally:
                stop.set()
                await serving

    asyncio.run(scenario())

    # The judge was asked for the one policy it holds, once.
    assert judge.asked == ["P-01"]
    # What it found reached the pull request, under the policy's own
    # summary.
    (comment,) = forge.comments.values()
    assert FOUND in comment
    assert "The description says what changed" in comment
    assert forge.labels
    # The journal holds the review, each fact naming the pull request.
    read = review_journal(database_url, None)
    (raised,) = read.events_for_pull_request(REF, FINDING_RAISED)
    assert raised.payload["policy_id"] == "P-01"
    assert raised.payload["clause"] == "EX-1"
    assert raised.payload["agent_id"] == "prose"
    (observed,) = read.events_for_pull_request(REF, PR_OBSERVED)
    assert observed.commit_sha == HEAD
    assert len(read.events_for_pull_request(REF, JUDGE_INVOKED)) == 1
    # The policy the manifest gives to a check was answered by the
    # check, which found no dash.
    (checked,) = read.events_for_pull_request(REF, POLICY_CHECKED)
    assert checked.payload["policy_id"] == "P-09"
    acted = read.events_for_pull_request(REF, ACTION_TAKEN)
    assert any(e.payload.get("performed") for e in acted)
    # The close read the conversation the comment started.
    (reaction,) = read.events_for_pull_request(REF, "reaction.recorded")
    assert reaction.payload["login"] == "a-reader"
    # Every row names the build and the deployment it was written
    # under.
    engine = sa.create_engine(engine_url(database_url))
    try:
        with engine.connect() as connection:
            stamps = {
                tuple(row)
                for row in connection.execute(
                    sa.select(
                        journal.c.build,
                        journal.c.policy_repository,
                        journal.c.policy_commit,
                    ).where(journal.c.pr_number == REF.number)
                )
            }
    finally:
        engine.dispose()
    assert stamps == {("b" * 40, REPOSITORY, "c" * 40)}
