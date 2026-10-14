"""Tests of a deployment with two reviewers whose runner is the judge:
each is judged on its own policies, with its own doctrine."""

import json
from typing import Any

import httpx2
import pytest

from bugflow.apps.worker.litellm_judge import LiteLLMJudge
from bugflow.apps.worker.review import declared_policies
from bugflow.apps.worker.reviewer_judges import (
    ReviewerJudges,
    judged_doctrine,
    judges_from_environment,
)
from bugflow.apps.worker.tests.policies import KEY, URL, deployed
from bugflow.method.tests.policy_files import (
    DOCTRINE,
    MANIFEST,
    POLICY,
    READ,
    TOPOLOGY,
)
from bugflow.review.domain.models.doctrine import DoctrineText
from bugflow.review.domain.models.submission import Submission

#: The second reviewer's doctrine, whose one clause the first's lacks.
CANON_DOCTRINE = "**EX-2.** A document says each thing in one place.\n"

#: Two reviewers the judge answers for, each with one policy and its
#: own doctrine.
TWO = READ | {
    "canon/reviewer.md": MANIFEST.replace("agent_id: prose", "agent_id: canon")
    .replace("governs: yes", "governs: no")
    .replace("policies: P-01", "policies: P-11"),
    "canon/policies/P-11-one-place.md": POLICY.replace(
        "policy_id: P-01", "policy_id: P-11"
    ).replace("clause: EX-1", "clause: EX-2"),
    "canon/doctrine/01-places.md": CANON_DOCTRINE,
}

SUBMISSION = Submission(
    title="Add a poller", body="Adds a poller.", commits=(), files=()
)

ANSWER = {
    "model": "small",
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": json.dumps({"violations": []}),
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
}


class Proxy:
    """Answers every request with no violation and keeps what it was
    sent."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.answer: dict[str, Any] = {"violations": []}

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append(json.loads(request.content))
        content = json.dumps(self.answer)
        return httpx2.Response(
            200,
            json=ANSWER
            | {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ]
            },
        )

    def system(self) -> str:
        (request,) = self.sent
        return str(request["messages"][0]["content"])


def judge_of(agent_id: str, proxy: Proxy) -> LiteLLMJudge:
    reviewers = deployed(TWO)
    return LiteLLMJudge(
        URL,
        KEY,
        policies=reviewers.agents[agent_id].policies,
        texts=reviewers.policies[agent_id],
        source=reviewers.policy_sources[agent_id],
        transport=httpx2.MockTransport(proxy),
        served={},
    )


def judges(proxy: Proxy) -> ReviewerJudges:
    return ReviewerJudges(
        {
            "prose": (judge_of("prose", proxy), DoctrineText(text=DOCTRINE)),
            "canon": (
                judge_of("canon", proxy),
                DoctrineText(text=CANON_DOCTRINE),
            ),
        }
    )


def test_every_reviewer_the_judge_runs_is_judged() -> None:
    judge = judges_from_environment({"LITELLM_MASTER_KEY": KEY}, deployed(TWO))
    assert isinstance(judge, ReviewerJudges)
    assert judge.policies == ("P-11", "P-01")
    assert declared_policies(deployed(TWO)) == ("P-01", "P-11")


@pytest.mark.parametrize(
    ("policy_id", "own", "other"),
    [("P-01", DOCTRINE, CANON_DOCTRINE), ("P-11", CANON_DOCTRINE, DOCTRINE)],
)
def test_a_policy_is_asked_with_its_own_reviewers_doctrine(
    policy_id: str, own: str, other: str
) -> None:
    proxy = Proxy()
    joined = DoctrineText(text=judged_doctrine(deployed(TWO)).text)
    judges(proxy).assess(SUBMISSION, joined, policy_id)
    assert own.strip() in proxy.system()
    assert other.strip() not in proxy.system()


def test_the_evaluation_quotes_a_clause_of_either_doctrine() -> None:
    doctrine = DoctrineText(text=judged_doctrine(deployed(TWO)).text)
    assert doctrine.clause("EX-1") == DOCTRINE.strip()
    assert doctrine.clause("EX-2") == CANON_DOCTRINE.strip()


def test_two_reviewers_may_not_name_the_same_policy() -> None:
    proxy = Proxy()
    prose = judge_of("prose", proxy)
    with pytest.raises(ValueError, match="P-01 is a policy of both"):
        ReviewerJudges(
            {
                "prose": (prose, DoctrineText(text=DOCTRINE)),
                "canon": (prose, DoctrineText(text=CANON_DOCTRINE)),
            }
        )


def test_one_judged_reviewer_keeps_its_judges_fingerprint() -> None:
    judge = judges_from_environment(
        {"LITELLM_MASTER_KEY": KEY}, deployed(READ)
    )
    assert isinstance(judge, ReviewerJudges)
    (alone,) = judge.judges.values()
    alone._served = {}
    assert judge.fingerprint == alone.fingerprint
    assert judged_doctrine(deployed(READ)).text == DOCTRINE


def test_two_judged_reviewers_have_a_fingerprint_of_their_own() -> None:
    proxy = Proxy()
    both = judges(proxy)
    assert both.fingerprint not in {
        judge.fingerprint for judge in both.judges.values()
    }


def test_a_deployment_with_no_judged_reviewer_judges_nothing() -> None:
    judge = judges_from_environment(
        {"LITELLM_MASTER_KEY": KEY}, deployed({"pace-layers.toml": TOPOLOGY})
    )
    assert isinstance(judge, LiteLLMJudge)
    assert judge.policies == ()


def test_without_a_key_there_are_no_judges() -> None:
    assert judges_from_environment({}, deployed(TWO)) is None


def test_a_finding_names_the_reviewer_whose_policy_it_is() -> None:
    proxy = Proxy()
    proxy.answer = {
        "violations": [
            {
                "clause": "EX-2",
                "quote": "Adds a poller.",
                "explanation": "Said twice.",
            }
        ]
    }
    joined = DoctrineText(text=judged_doctrine(deployed(TWO)).text)
    (finding,) = judges(proxy).assess(SUBMISSION, joined, "P-11").findings
    assert finding.agent_id == "canon"
