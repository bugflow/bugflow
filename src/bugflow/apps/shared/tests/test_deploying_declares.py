"""Deploying writes the declarations the deployment carries. The use
case itself is the method context's, tested there."""

from datetime import UTC, datetime

from bugflow.apps.shared.deploying import (
    CHECKS_VARIABLE,
    Deploying,
    checks_from,
    deploying_with,
)
from bugflow.method.dtos.deploy_policies import (
    DeployPoliciesRequest,
    PolicyFile,
)
from bugflow.method.infrastructure.in_memory_policy_deployments import (
    InMemoryPolicyDeployments,
)
from bugflow.method.tests.policy_files import READ
from bugflow.review.domain.models.review_declaration import (
    DispatchedProcesses,
    JudgedPolicies,
)
from bugflow.review.infrastructure.in_memory_review_declaration import (
    InMemoryDispatchedProcesses,
    InMemoryJudgedPolicies,
)
from bugflow.shared.infrastructure.in_memory_journal import InMemoryJournal

REPOSITORY = "example-org/pull-request-policies"
WIDGETS = ("github", "example-org/widgets")
DECLARING = READ | {
    "declarations.toml": '[repository."example-org/widgets"]\n'
    'policies = ["P-01"]\n'
    'processes = ["evaluate-pull-request"]\n'
}


class Fixture:
    def __init__(self) -> None:
        self.deployments = InMemoryPolicyDeployments()
        self.journal = InMemoryJournal()
        self.judged = InMemoryJudgedPolicies()
        self.dispatched = InMemoryDispatchedProcesses()
        self.deploying: Deploying = deploying_with(
            self.deployments, self.journal, self.judged, self.dispatched, ()
        )

    def deploy(
        self,
        commit: str = "c1",
        files: dict[str, str] | None = None,
        check_only: bool = False,
    ) -> str:
        return self.deploying.deploy.execute(
            DeployPoliciesRequest(
                repository=REPOSITORY,
                commit=commit,
                files=tuple(
                    PolicyFile(path=path, text=text)
                    for path, text in (
                        READ if files is None else files
                    ).items()
                ),
                check_only=check_only,
                sent_by="a test",
            )
        ).outcome


def test_deploying_writes_the_declarations() -> None:
    fixture = Fixture()
    assert fixture.deploy(files=DECLARING) == "deployed"
    assert fixture.judged.judged(*WIDGETS) == {"P-01"}
    assert fixture.dispatched.dispatched(*WIDGETS) == {"evaluate-pull-request"}


def test_a_deployment_without_the_file_leaves_the_declarations() -> None:
    fixture = Fixture()
    fixture.judged.declare(JudgedPolicies(forge="github", repo="o/r"))
    fixture.deploy()
    assert fixture.judged.declarations() == [
        JudgedPolicies(forge="github", repo="o/r")
    ]


def test_a_repository_the_file_leaves_out_is_reviewed_for_nothing() -> None:
    fixture = Fixture()
    fixture.judged.declare(
        JudgedPolicies(forge="github", repo="o/r", policies=("P-01",))
    )
    fixture.dispatched.declare(
        DispatchedProcesses(
            forge="github", repo="o/r", processes=("evaluate-pull-request",)
        )
    )
    fixture.deploy(files=DECLARING)
    assert fixture.judged.judged("github", "o/r") == frozenset()
    assert fixture.dispatched.dispatched("github", "o/r") == frozenset()


def test_a_check_writes_no_declaration() -> None:
    fixture = Fixture()
    assert fixture.deploy(files=DECLARING, check_only=True) == "checked"
    assert fixture.judged.declarations() == []
    assert fixture.journal.entries == []


def test_sending_the_deployment_again_writes_its_declarations_again() -> None:
    """So a call that stored the deployment and failed before the
    declarations were written is completed by repeating it."""
    fixture = Fixture()
    fixture.deploy(files=DECLARING)
    fixture.judged.declare(JudgedPolicies(forge=WIDGETS[0], repo=WIDGETS[1]))
    assert fixture.deploy(files=DECLARING) == "already_in_force"
    assert fixture.judged.judged(*WIDGETS) == {"P-01"}
    assert len(fixture.journal.entries) == 1


def test_the_fact_is_recorded_at_the_time_of_the_clock() -> None:
    fixture = Fixture()
    before = datetime.now(UTC)
    fixture.deploy()
    (fact,) = fixture.journal.entries
    assert fact.occurred_at >= before
    assert fact.payload["sent_by"] == "a test"


def test_the_checks_are_read_from_the_environment() -> None:
    assert checks_from({}) == ("em-dash",)
    assert checks_from({CHECKS_VARIABLE: ""}) == ()
    assert checks_from({CHECKS_VARIABLE: "em-dash, other ,"}) == (
        "em-dash",
        "other",
    )
