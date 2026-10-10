"""Tests of the classes of model: which model answers for which policy.

Three things have to agree: the class each policy names, the settings
that give a class its model, and the models the proxy publishes.
"""

import httpx2
import pytest

from bugflow.apps.worker import litellm_judge
from bugflow.apps.worker.litellm_judge import (
    DEFAULT_URL,
    MODEL_CLASS_DEFAULTS,
    MODEL_CLASS_VARIABLES,
    LiteLLMJudge,
    judge_from_environment,
    judging_agent,
    model_classes_from_environment,
)
from bugflow.apps.worker.tests.policies import (
    FILES,
    KEY,
    POLICIES,
    SOURCE,
    a_judge,
    deployed,
    publishing,
)
from bugflow.method.tests.policy_files import MANIFEST, READ, TOPOLOGY
from bugflow.review.domain.errors import (
    JudgeTemporarilyUnavailableError,
    JudgeUnavailableError,
)

#: A reviewer the judge answers for, with the example policies. The
#: last of its policies is answered by a check and has no file.
JUDGED = """\
agent_id: prose
summary: What a change says about itself
runner: judge
governs: yes
policies: P-03, P-02, P-09
checks: em-dash P-09 EX-21
---

Reads what a change says about itself.
"""

#: A reviewer a checkout runner runs, which the judge does not answer
#: for.
CHECKOUT = """\
agent_id: security
summary: Whether a change makes the system easier to attack
runner: managed-agent
governs: no
---

Reads the change for security.
"""

DEPLOYED = {
    "pace-layers.toml": TOPOLOGY,
    "prose/reviewer.md": JUDGED,
    "security/reviewer.md": CHECKOUT,
} | {f"prose/policies/{name}": text for name, text in FILES.items()}


def test_every_class_a_policy_names_has_a_setting_and_a_default() -> None:
    named = {policy.model_class for policy in POLICIES.values()}
    assert named <= set(MODEL_CLASS_VARIABLES)
    assert set(MODEL_CLASS_VARIABLES) == set(MODEL_CLASS_DEFAULTS)


def test_no_default_names_a_model() -> None:
    """A class with no setting asks the proxy for the role of its own
    name, so the code names no vendor's model."""
    assert MODEL_CLASS_DEFAULTS == {
        "small": "small",
        "medium": "medium",
        "large": "large",
    }
    assert MODEL_CLASS_VARIABLES == {
        "small": "LLM_MODEL_SMALL",
        "medium": "LLM_MODEL_MEDIUM",
        "large": "LLM_MODEL_LARGE",
    }


def test_a_class_reads_its_setting_and_falls_back_to_its_default() -> None:
    classes = model_classes_from_environment({"LLM_MODEL_MEDIUM": "a-model"})
    assert classes["medium"] == "a-model"
    assert classes["small"] == MODEL_CLASS_DEFAULTS["small"]


def test_without_a_key_there_is_no_judge() -> None:
    assert judge_from_environment({}, deployed(DEPLOYED)) is None


def test_the_judge_answers_for_the_reviewer_that_names_it() -> None:
    assert judging_agent(deployed(DEPLOYED)) == "prose"
    assert (
        judging_agent(
            deployed(
                {
                    "pace-layers.toml": TOPOLOGY,
                    "security/reviewer.md": CHECKOUT,
                }
            )
        )
        is None
    )


def test_the_judge_judges_the_deployed_policies_its_reviewer_names() -> None:
    """In the manifest's order. A policy a check answers has no text and
    is not judged, and a policy the manifest does not name is not
    either."""
    judge = judge_from_environment(
        {"LITELLM_MASTER_KEY": KEY}, deployed(DEPLOYED)
    )
    assert judge is not None
    assert judge.policies == ("P-03", "P-02")
    assert judge.policy("P-02").instructions == POLICIES["P-02"].instructions


def test_the_judge_is_fingerprinted_with_the_deployed_text() -> None:
    environ = {"LITELLM_MASTER_KEY": KEY}
    judge = judge_from_environment(environ, deployed(DEPLOYED))
    assert judge is not None
    same = LiteLLMJudge(
        DEFAULT_URL,
        KEY,
        policies=("P-03", "P-02"),
        texts=deployed(DEPLOYED).policies["prose"],
        source=SOURCE,
    )
    edited = DEPLOYED | {
        "prose/policies/P-02-scope.md": FILES["P-02-scope.md"].replace(
            "does one thing.\n", "does one thing only.\n"
        )
    }
    other = judge_from_environment(environ, deployed(edited))
    assert other is not None
    for one in (judge, same, other):
        one._served = {}
    assert judge.fingerprint == same.fingerprint
    assert judge.fingerprint != other.fingerprint


def test_a_server_never_sent_a_deployment_judges_nothing() -> None:
    judge = judge_from_environment({"LITELLM_MASTER_KEY": KEY}, None)
    assert judge is not None
    assert judge.policies == ()


def test_a_deployment_with_one_policy_is_judged_on_it() -> None:
    assert MANIFEST.count("policies: P-01") == 1
    judge = judge_from_environment({"LITELLM_MASTER_KEY": KEY}, deployed(READ))
    assert judge is not None
    assert judge.policies == ("P-01",)
    assert judge.model_for("P-01") == "small"


def test_a_policy_is_judged_by_its_classs_model() -> None:
    judge = judge_from_environment(
        {
            "LITELLM_MASTER_KEY": KEY,
            "LLM_MODEL_SMALL": "a-small-model",
            "LLM_MODEL_LARGE": "a-large-model",
        },
        deployed(DEPLOYED),
    )
    assert judge is not None
    assert judge.model_for("P-02") == "a-small-model"
    assert judge.model_for("P-03") == "a-large-model"


def test_judge_model_overrides_every_class() -> None:
    judge = judge_from_environment(
        {
            "LITELLM_MASTER_KEY": KEY,
            "JUDGE_MODEL": "one-model",
            "LLM_MODEL_SMALL": "a-small-model",
        },
        deployed(DEPLOYED),
    )
    assert judge is not None
    assert judge.model_for("P-03") == judge.model_for("P-02") == "one-model"


def test_the_fingerprint_follows_a_classs_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A class pointed at another model is another judge."""
    monkeypatch.setattr(litellm_judge, "served_by", lambda client: {})
    environ = {"LITELLM_MASTER_KEY": KEY}
    before = judge_from_environment(environ, deployed(DEPLOYED))
    after = judge_from_environment(
        environ | {"LLM_MODEL_SMALL": "another-model"}, deployed(DEPLOYED)
    )
    assert before is not None and after is not None
    assert before.fingerprint != after.fingerprint


def test_a_class_naming_an_unpublished_model_is_refused() -> None:
    judge = a_judge(
        policies=("P-01",),
        model_classes={
            "medium": "a-model",
            "small": "a-fiction",
            "large": "a-model",
        },
        transport=publishing("a-model"),
    )
    with pytest.raises(JudgeUnavailableError, match="small names a-fiction"):
        judge.check_model_classes()


def test_classes_naming_published_models_pass() -> None:
    judge = a_judge(
        policies=("P-01",),
        model_classes={
            "medium": "a-model",
            "small": "b-model",
            "large": "a-model",
        },
        transport=publishing("a-model", "b-model"),
    )
    judge.check_model_classes()
    assert judge.published_models() == ["a-model", "b-model"]


def test_a_proxy_that_cannot_be_reached_is_temporarily_unavailable() -> None:
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    judge = a_judge(
        policies=("P-01",),
        model_classes={"medium": "a-model"},
        transport=httpx2.MockTransport(refuse),
    )
    with pytest.raises(JudgeTemporarilyUnavailableError):
        judge.check_model_classes()


def judge_supplying(published: list[str], **classes: str) -> LiteLLMJudge:
    return a_judge(
        policies=("P-03", "P-02"),
        model_classes={"small": "", "medium": "", "large": "", **classes},
        transport=publishing(*published),
    )


def test_a_class_with_no_model_supplies_nothing() -> None:
    """An empty setting is not a mistyped one. It says this server has
    no model of that class."""
    judge = judge_supplying(["a-model"], small="a-model")
    assert judge.supplied_classes() == {"small"}
    judge.check_model_classes()


def test_a_policy_whose_class_is_unsupplied_is_not_judged() -> None:
    """Left in the set it would be asked, fail for want of a model, and
    leave the pull request unknown, which is a different claim."""
    judge = judge_supplying(["a-model"], small="a-model")
    assert judge.unsupplied_policies() == ("P-03",)
    assert judge.drop_unsupplied_policies() == ("P-03",)
    assert judge.policies == ("P-02",)


def test_dropping_twice_drops_nothing_the_second_time() -> None:
    judge = judge_supplying(["a-model"], small="a-model")
    judge.drop_unsupplied_policies()
    assert judge.drop_unsupplied_policies() == ()


def test_a_class_naming_a_model_the_proxy_lacks_still_fails() -> None:
    """Empty is a decision. Wrong is a mistake, and stays a refusal."""
    judge = judge_supplying(["a-model"], small="a-fiction")
    with pytest.raises(JudgeUnavailableError, match="small names a-fiction"):
        judge.check_model_classes()


def test_a_policy_naming_a_class_nothing_defines_is_refused() -> None:
    with pytest.raises(ValueError, match="no class of model named large"):
        a_judge(policies=("P-03",), model_classes={"small": "a-model"})


def test_the_fingerprint_follows_the_model_behind_a_role() -> None:
    """Pointing a role at another model in the proxy's configuration is a
    new judge. The role's name is not what decides a judgement."""
    one = a_judge(policies=("P-01",), served={"medium": "model-a"})
    other = a_judge(policies=("P-01",), served={"medium": "model-b"})
    assert one.fingerprint != other.fingerprint


def test_a_role_renamed_over_the_same_model_is_the_same_judge() -> None:
    by_name = a_judge(
        policies=("P-01",),
        model_classes={"small": "m-s", "medium": "m-m", "large": "m-l"},
    )
    by_role = a_judge(
        policies=("P-01",),
        served={"small": "m-s", "medium": "m-m", "large": "m-l"},
    )
    assert by_name.fingerprint == by_role.fingerprint


def test_a_finding_names_the_model_that_answered_not_the_role() -> None:
    judge = a_judge(policies=("P-01",), served={"medium": "model-a"})
    assert judge.answering("medium") == "model-a"
    assert judge.answering("model-b") == "model-b"
