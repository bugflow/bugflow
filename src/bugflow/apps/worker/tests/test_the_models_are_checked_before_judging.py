"""Tests of the check a worker makes of its judge before it serves:
that each class of model names a model the proxy publishes, and that
every policy a reviewer declared has a model."""

import httpx2
import pytest

from bugflow.apps.worker.activities import ReviewActivities
from bugflow.apps.worker.litellm_judge import LiteLLMJudge
from bugflow.apps.worker.review import check_judging_models
from bugflow.apps.worker.tests.activities import REPO
from bugflow.apps.worker.tests.policies import a_judge, publishing
from bugflow.review.domain.errors import JudgeTemporarilyUnavailableError


def judge_supplying(published: list[str], **classes: str) -> LiteLLMJudge:
    """A judge of a policy of the large class and one of the small,
    where only the classes named have a model."""
    return a_judge(
        policies=("P-03", "P-02"),
        model_classes={"small": "", "medium": "", "large": "", **classes},
        transport=publishing(*published),
    )


def test_a_mistyped_class_stops_the_worker() -> None:
    judge = a_judge(
        policies=("P-01",),
        model_classes={"medium": "a-fiction"},
        transport=publishing(),
    )
    with pytest.raises(ValueError, match="medium names a-fiction"):
        check_judging_models(judge)


def test_a_proxy_that_cannot_be_reached_yet_does_not_stop_the_worker() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    judge = a_judge(
        policies=("P-01",),
        model_classes={"medium": "a-model"},
        transport=httpx2.MockTransport(refuse),
    )
    said: list[str] = []

    check_judging_models(judge, warn=said.append)

    (warning,) = said
    assert "unchecked" in warning and "connection refused" in warning
    with pytest.raises(JudgeTemporarilyUnavailableError):
        judge.check_model_classes()


def test_without_a_judge_there_is_nothing_to_check() -> None:
    said: list[str] = []
    check_judging_models(None, warn=said.append)
    assert said == []


def test_a_declared_policy_with_no_model_stops_the_worker() -> None:
    """A reviewer's verdict covers what it declared, so a policy it
    declared and cannot have judged is a refusal and not a quieter
    review."""
    judge = judge_supplying(["a-model"], small="a-model")
    with pytest.raises(ValueError, match="declared by an installed reviewer"):
        check_judging_models(judge, declared=["P-03"])


def test_a_skipped_policy_nobody_declared_is_named_and_not_refused() -> None:
    said: list[str] = []
    judge = judge_supplying(["a-model"], small="a-model")
    check_judging_models(judge, declared=["P-02"], warn=said.append)
    assert any("P-03" in line for line in said)


def test_declaring_nothing_leaves_the_note() -> None:
    said: list[str] = []
    judge = judge_supplying(["a-model"], small="a-model")
    check_judging_models(judge, warn=said.append)
    assert any("P-03" in line for line in said)


def composed(published: list[str], **classes: str) -> ReviewActivities:
    """The activities over such a judge, as the worker builds them.

    The check is handed what the activities hold as their judge. If
    that were the activity that calls the judge, the check would return
    at once, nothing would be dropped, and the fan-out would ask a
    policy that has no model.
    """
    return ReviewActivities(
        forge=None,  # type: ignore[arg-type]
        doctrine=None,  # type: ignore[arg-type]
        judge=judge_supplying(published, **classes),
        journal=None,  # type: ignore[arg-type]
        snapshots=None,  # type: ignore[arg-type]
        clock=None,  # type: ignore[arg-type]
        archive=None,  # type: ignore[arg-type]
    )


def test_the_check_is_handed_the_judge_and_not_the_activity() -> None:
    activities = composed(["a-model"], small="a-model")
    assert isinstance(activities.judge_port, LiteLLMJudge)


def test_a_policy_with_no_model_is_never_fanned_out_to() -> None:
    """Left in the fan-out it would be asked, fail for want of a model,
    and leave the pull request unknown, which says the judge could not
    answer when this server supplies no model of its class."""
    activities = composed(["a-model"], small="a-model")
    said: list[str] = []

    check_judging_models(activities.judge_port, warn=said.append)

    assert activities.judge_policies("github", REPO) == ["P-02"]
    assert said and "P-03" in said[0]


def test_every_policy_is_fanned_out_to_when_every_class_is_supplied() -> None:
    activities = composed(["a-model"], small="a-model", large="a-model")
    check_judging_models(activities.judge_port, warn=lambda _: None)
    assert activities.judge_policies("github", REPO) == ["P-03", "P-02"]
