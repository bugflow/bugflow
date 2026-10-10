"""Deploying policies through the two routes a pipeline calls, and
writing the declarations the deployment carries. The use case itself
is the method context's, tested there."""

import pytest

from bugflow.apps.api.role_policy_deployment_access import (
    RolePolicyDeploymentAccess,
)
from bugflow.apps.api.tests.doubles import DEPLOYER, READER, Server, bearer
from bugflow.method.tests.policy_files import MANIFEST, READ
from bugflow.shared.domain.values.caller import Caller

REPOSITORY = "example-org/pull-request-policies"
ROUTE = "/api/policy-deployments"
IN_FORCE = "/api/policy-deployments/in-force"


def body(
    commit: str = "c1",
    files: dict[str, str] | None = None,
    **changes: object,
) -> dict[str, object]:
    return {
        "repository": REPOSITORY,
        "commit": commit,
        "files": [
            {"path": p, "text": t}
            for p, t in (READ if files is None else files).items()
        ],
    } | changes


def test_the_healthcheck_needs_no_token() -> None:
    server = Server()
    assert server.client.get("/").json() == {"ok": True}
    assert server.client.get("/api/healthcheck").json() == {"ok": True}


def test_the_deployers_role_deploys_through_the_api() -> None:
    server = Server()
    answered = server.client.post(ROUTE, json=body(), headers=bearer(DEPLOYER))
    assert answered.status_code == 200
    assert answered.json()["outcome"] == "deployed"
    assert answered.json()["in_force"]["commit"] == "c1"
    (fact,) = server.journal.entries
    assert (
        fact.payload["sent_by"] == "machine-user-1 through policies-pipeline"
    )


def test_repeating_the_call_changes_nothing() -> None:
    server = Server()
    server.client.post(ROUTE, json=body(), headers=bearer(DEPLOYER))
    again = server.client.post(ROUTE, json=body(), headers=bearer(DEPLOYER))
    assert again.status_code == 200
    assert again.json()["outcome"] == "already_in_force"
    assert len(server.journal.entries) == 1


def test_a_check_through_the_api_stores_nothing() -> None:
    server = Server()
    answered = server.client.post(
        ROUTE, json=body(check_only=True), headers=bearer(DEPLOYER)
    )
    assert answered.status_code == 200
    assert answered.json()["outcome"] == "checked"
    assert server.deployments.in_force() is None


@pytest.mark.parametrize("role", [READER, "nobody"])
def test_a_caller_without_the_deployers_role_is_refused(role: str) -> None:
    server = Server()
    posted = server.client.post(ROUTE, json=body(), headers=bearer(role))
    read = server.client.get(IN_FORCE, headers=bearer(role))
    assert posted.status_code == 403
    assert read.status_code == 403
    assert server.deployments.in_force() is None


def test_a_call_without_a_token_is_refused() -> None:
    server = Server()
    none = server.client.post(ROUTE, json=body())
    assert none.status_code == 401
    assert none.headers["WWW-Authenticate"] == "Bearer"
    refused = server.client.post(ROUTE, json=body(), headers=bearer("refused"))
    assert refused.status_code == 401
    basic = server.client.post(
        ROUTE, json=body(), headers={"Authorization": "Basic abc"}
    )
    assert basic.status_code == 401


def test_files_that_do_not_parse_answer_422_with_every_problem() -> None:
    server = Server()
    broken = body(
        files={
            "notes.txt": "x",
            "prose/reviewer.md": "agent_id: prose\n",
        }
    )
    answered = server.client.post(ROUTE, json=broken, headers=bearer(DEPLOYER))
    assert answered.status_code == 422
    assert "notes.txt" in answered.json()["detail"]
    assert "prose/reviewer.md" in answered.json()["detail"]
    assert server.deployments.in_force() is None


def test_a_commit_held_with_other_content_answers_409() -> None:
    server = Server()
    server.client.post(ROUTE, json=body(), headers=bearer(DEPLOYER))
    changed = body(files=READ | {"prose/reviewer.md": MANIFEST + "Changed.\n"})
    answered = server.client.post(
        ROUTE, json=changed, headers=bearer(DEPLOYER)
    )
    assert answered.status_code == 409
    in_force = server.deployments.in_force()
    assert in_force is not None
    assert in_force.text_of("prose/reviewer.md") == MANIFEST


def test_the_deployment_in_force_can_be_read() -> None:
    server = Server()
    none = server.client.get(IN_FORCE, headers=bearer(DEPLOYER))
    assert none.status_code == 404
    posted = server.client.post(ROUTE, json=body(), headers=bearer(DEPLOYER))
    read = server.client.get(IN_FORCE, headers=bearer(DEPLOYER))
    assert read.status_code == 200
    assert read.json() == posted.json()["in_force"]


def test_the_role_that_deploys_is_the_one_given() -> None:
    access = RolePolicyDeploymentAccess("may-deploy")
    holding = Caller(subject="s", client="c", roles=frozenset({"may-deploy"}))
    other = Caller(subject="s", client="c", roles=frozenset({"other"}))
    assert access.may_deploy(holding)
    assert not access.may_deploy(other)


DECLARING = READ | {
    "declarations.toml": '[repository."example-org/widgets"]\n'
    'policies = ["P-01"]\n'
}


def test_deploying_through_the_api_writes_the_declarations() -> None:
    server = Server()
    answered = server.client.post(
        ROUTE, json=body(files=DECLARING), headers=bearer(DEPLOYER)
    )
    assert answered.status_code == 200
    assert server.judged.judged("github", "example-org/widgets") == {"P-01"}


def test_a_check_through_the_api_writes_no_declaration() -> None:
    server = Server()
    server.client.post(
        ROUTE,
        json=body(files=DECLARING, check_only=True),
        headers=bearer(DEPLOYER),
    )
    assert server.judged.declarations() == []
