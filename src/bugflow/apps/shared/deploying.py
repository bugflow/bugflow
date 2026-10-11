"""Deploying policies, composed: the use case that stores a deployment
and puts it in force, joined to the declarations it carries.

The use case is the method context's and the declaration records are
the review context's, so the two are joined here, where both may be
imported. The API's route and the command's ``install-policies`` run
the same composition, so a deployment made on the host is checked and
recorded as one a pipeline sends is.
"""

import sys
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from bugflow.apps.shared.journals import stamped_journal
from bugflow.method.domain.errors import (
    PolicyDeploymentConflictError,
    PolicyDeploymentError,
)
from bugflow.method.domain.models.policy_deployment import PolicyDeployment
from bugflow.method.domain.repositories.policy_deployment import (
    PolicyDeploymentRepository,
)
from bugflow.method.dtos.deploy_policies import (
    DeployPoliciesRequest,
    DeployPoliciesResponse,
    PolicyFile,
)
from bugflow.method.infrastructure.policy_deployment_parsing import (
    DECLARATIONS,
    ParsedPolicyDeploymentCheck,
    parse_deployment,
)
from bugflow.method.infrastructure.policy_directory import PolicyDirectory
from bugflow.method.infrastructure.sqlalchemy_policy_deployments import (
    SqlAlchemyPolicyDeployments,
)
from bugflow.method.usecases.deploy_policies import DeployPoliciesUseCase
from bugflow.review.domain.models.review_declaration import (
    DispatchedProcesses,
    JudgedPolicies,
)
from bugflow.review.domain.services.review_declaration import (
    DispatchedProcessesService,
    JudgedPoliciesService,
)
from bugflow.review.domain.values.checked_policy import CHECKS
from bugflow.review.infrastructure.sqlalchemy_review_declaration import (
    SqlAlchemyDispatchedProcesses,
    SqlAlchemyJudgedPolicies,
)
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.infrastructure.system_clock import SystemClock

#: The setting that names the checks this server performs, comma-
#: separated. Unset, the server performs none, and a manifest naming
#: one is refused.
CHECKS_VARIABLE = "POLICY_CHECKS"


def checks_from(environ: Mapping[str, str]) -> tuple[str, ...]:
    """Return the names of the checks this server performs: the ones the
    package has, unless ``POLICY_CHECKS`` lists them."""
    if CHECKS_VARIABLE not in environ:
        return CHECKS
    return tuple(
        name.strip()
        for name in environ[CHECKS_VARIABLE].split(",")
        if name.strip()
    )


def deployment_check(checks: Collection[str]) -> ParsedPolicyDeploymentCheck:
    """Return the check a deployment passes before it is stored: the
    parse, told which checks this server has, so a manifest naming
    another is refused."""
    return ParsedPolicyDeploymentCheck(checks)


def apply_declarations(
    deployment: PolicyDeployment,
    judged: JudgedPoliciesService,
    dispatched: DispatchedProcessesService,
    checks: Collection[str],
) -> bool:
    """Write a deployment's declarations file to the declaration records.

    Returns False, and writes nothing, when the deployment has no such
    file: the server's declarations are then whatever was declared
    before.

    With the file, it is the whole of what the server reviews. Each
    repository in it has its judged policies and its dispatched
    processes replaced, and a repository that has a declaration and is
    not in the file has both emptied, so it is reviewed for nothing.
    Writing the same file twice changes nothing.
    """
    declared = parse_deployment(deployment, checks).declared
    if declared is None:
        return False
    named = {(one.forge, one.repo) for one in declared}
    for one in declared:
        judged.declare(
            JudgedPolicies(
                forge=one.forge, repo=one.repo, policies=one.policies
            )
        )
        dispatched.declare(
            DispatchedProcesses(
                forge=one.forge, repo=one.repo, processes=one.processes
            )
        )
    for held in judged.declarations():
        if (held.forge, held.repo) not in named:
            judged.declare(JudgedPolicies(forge=held.forge, repo=held.repo))
    for sent in dispatched.declarations():
        if (sent.forge, sent.repo) not in named:
            dispatched.declare(
                DispatchedProcesses(forge=sent.forge, repo=sent.repo)
            )
    return True


def declared_by_deployment(deployments: PolicyDeploymentRepository) -> bool:
    """Return whether the deployment in force carries a declarations
    file.

    When it does, what each repository is judged on and dispatches
    comes from the policy repository, and the next deployment writes
    it again. A command that changed it on the host would be undone
    then, so ``bugflow declare`` refuses to.
    """
    in_force = deployments.in_force()
    return in_force is not None and in_force.text_of(DECLARATIONS) is not None


class DeployPoliciesAndDeclare:
    """Runs ``DeployPoliciesUseCase``, then writes the deployment's
    declarations.

    The declarations are written whenever the deployment is in force
    afterwards, including when it already was, so a call that failed
    between the two is completed by sending it again. A check writes
    nothing.
    """

    def __init__(
        self,
        deploy: DeployPoliciesUseCase,
        deployments: PolicyDeploymentRepository,
        judged: JudgedPoliciesService,
        dispatched: DispatchedProcessesService,
        checks: Collection[str],
    ) -> None:
        self._deploy = deploy
        self._deployments = deployments
        self._judged = judged
        self._dispatched = dispatched
        self._checks = checks

    def execute(
        self, request: DeployPoliciesRequest
    ) -> DeployPoliciesResponse:
        answered = self._deploy.execute(request)
        if answered.outcome != "checked":
            in_force = self._deployments.in_force()
            if in_force is not None:
                apply_declarations(
                    in_force, self._judged, self._dispatched, self._checks
                )
        return answered


@dataclass(frozen=True)
class Deploying:
    """What deploys: the composed use case, and where deployments are
    kept, which answers what is in force."""

    deploy: DeployPoliciesAndDeclare
    deployments: PolicyDeploymentRepository


def deploying_with(
    deployments: PolicyDeploymentRepository,
    recording: RecordingService,
    judged: JudgedPoliciesService,
    dispatched: DispatchedProcessesService,
    checks: Collection[str],
) -> Deploying:
    """Compose deploying over the stores given. For a test, or a program
    that holds the stores already."""
    return Deploying(
        deploy=DeployPoliciesAndDeclare(
            DeployPoliciesUseCase(
                deployments, deployment_check(checks), recording, SystemClock()
            ),
            deployments,
            judged,
            dispatched,
            checks,
        ),
        deployments=deployments,
    )


def deploying_over(
    database_url: str, build: str | None, checks: Collection[str]
) -> Deploying:
    """Compose deploying over the Postgres stores, the journal stamped
    with ``build``."""
    return deploying_with(
        SqlAlchemyPolicyDeployments(database_url),
        stamped_journal(database_url, build),
        SqlAlchemyJudgedPolicies(database_url),
        SqlAlchemyDispatchedProcesses(database_url),
        checks,
    )


#: What the fact records as the sender of a deployment made on the host.
INSTALLED_ON_THE_HOST = "bugflow install-policies on the host"


def run_install_policies(
    directory: Path,
    repository: str,
    commit: str,
    deploying: Deploying,
    checks: Collection[str],
    out: TextIO | None = None,
    check_only: bool = False,
) -> int:
    """Store what the directory holds and put it in force; 0 when the
    database holds it afterwards. With ``check_only``, parse it and
    store nothing; 0 when it parses.

    Prints what the database holds afterwards, read back and not
    echoed.
    """
    out = out or sys.stdout
    if not directory.is_dir():
        print(f"error: {directory} is not a directory", file=sys.stderr)
        return 2
    read = PolicyDirectory(directory).read(repository, commit)
    try:
        answered = deploying.deploy.execute(
            DeployPoliciesRequest(
                repository=repository,
                commit=commit,
                files=tuple(
                    PolicyFile(path=one.path, text=one.text)
                    for one in read.files
                ),
                sent_by=INSTALLED_ON_THE_HOST,
                check_only=check_only,
            )
        )
    except (PolicyDeploymentError, PolicyDeploymentConflictError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if check_only:
        print(
            f"checked {len(read.files)} files, content "
            f"{answered.content_hash[:12]}; nothing stored",
            file=out,
        )
        return 0
    now = deploying.deployments.in_force()
    if now is None:
        print("error: nothing is in force after the write", file=sys.stderr)
        return 1
    print(
        f"{now.repository} at {now.commit} is in force, "
        f"{len(now.files)} files, content {now.content_hash[:12]}"
        + ("" if answered.outcome == "deployed" else "; it already was"),
        file=out,
    )
    for one in now.files:
        print(f"  {one.path}", file=out)
    declared = parse_deployment(now, checks).declared
    if declared is not None:
        print(
            f"{len(declared)} repositories are declared by "
            f"{DECLARATIONS}; any other has its declaration emptied",
            file=out,
        )
    return 0
