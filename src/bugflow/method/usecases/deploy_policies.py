"""Use case: keep the files a policy repository sent, and put them in
force.

The files are checked, stored and put in force, and a fact records it.
Asked to check only, the files are checked and nothing is stored or
recorded.
"""

from bugflow.method.domain.facts import POLICIES_DEPLOYED
from bugflow.method.domain.models.policy_deployment import (
    DeployedFile,
    PolicyDeployment,
    PutInForce,
)
from bugflow.method.domain.repositories.policy_deployment import (
    PolicyDeploymentRepository,
)
from bugflow.method.domain.services.policy_deployment_check import (
    PolicyDeploymentCheckService,
)
from bugflow.method.dtos.deploy_policies import (
    DeployPoliciesRequest,
    DeployPoliciesResponse,
    InForce,
)
from bugflow.shared.domain.models.journal_entry import JournalEntry, event_id
from bugflow.shared.domain.services.clock import ClockService
from bugflow.shared.domain.services.recording import RecordingService
from bugflow.shared.domain.values.correlation import Correlation

#: The workflow id the fact is recorded under. A deployment is sent by a
#: pipeline or typed on the host, and is not run in a workflow.
WORKFLOW_ID = "policies/deploy"


class DeployPoliciesUseCase:
    """Takes the files of a deployment. Returns whether it was put in
    force and which deployment is in force now.

    Raises ``PolicyDeploymentError`` if the files are not a deployment
    or do not parse, and ``PolicyDeploymentConflictError`` if the commit
    is already held with other content. In both cases nothing is stored
    and the deployment in force stays in force.
    """

    def __init__(
        self,
        deployments: PolicyDeploymentRepository,
        check: PolicyDeploymentCheckService,
        recording: RecordingService,
        clock: ClockService,
    ) -> None:
        self._deployments = deployments
        self._check = check
        self._recording = recording
        self._clock = clock

    def execute(
        self, request: DeployPoliciesRequest
    ) -> DeployPoliciesResponse:
        deployment = PolicyDeployment(
            repository=request.repository,
            commit=request.commit,
            files=tuple(
                DeployedFile(path=one.path, text=one.text)
                for one in request.files
            ),
        )
        self._check.check(deployment)
        if request.check_only:
            return DeployPoliciesResponse(
                outcome="checked",
                content_hash=deployment.content_hash,
                in_force=self._in_force(),
            )
        replaced = self._deployments.last_put_in_force()
        changed = self._deployments.deploy(deployment)
        if changed:
            self._recording.append(
                [self._fact(deployment, request.sent_by, replaced)]
            )
        return DeployPoliciesResponse(
            outcome="deployed" if changed else "already_in_force",
            content_hash=deployment.content_hash,
            in_force=self._in_force(),
        )

    def _in_force(self) -> InForce | None:
        latest = self._deployments.last_put_in_force()
        if latest is None:
            return None
        return InForce(
            repository=latest.repository,
            commit=latest.commit,
            content_hash=latest.content_hash,
        )

    def _fact(
        self,
        deployment: PolicyDeployment,
        sent_by: str,
        replaced: PutInForce | None,
    ) -> JournalEntry:
        now = self._clock.now()
        # The time is part of the fact's id, because the same commit can
        # be put in force more than once and each time is a fact.
        correlation = Correlation(
            workflow_id=WORKFLOW_ID,
            run_id=f"{deployment.repository}@{deployment.commit}",
        )
        return JournalEntry(
            event_id=event_id(correlation, POLICIES_DEPLOYED, now.isoformat()),
            occurred_at=now,
            event_type=POLICIES_DEPLOYED,
            # A deployment is about no repository under review. Naming
            # one would let a query that forgets a filter count it as a
            # review of that repository.
            forge="",
            repo="",
            pr_number=None,
            commit_sha=None,
            corpus_version=None,
            workflow_id=correlation.workflow_id,
            run_id=correlation.run_id,
            payload={
                "repository": deployment.repository,
                "commit": deployment.commit,
                "content_hash": deployment.content_hash,
                "files": len(deployment.files),
                "sent_by": sent_by,
                # The deployment that was in force before, or None if
                # this is the server's first.
                "replaced": None
                if replaced is None
                else {
                    "repository": replaced.repository,
                    "commit": replaced.commit,
                    "content_hash": replaced.content_hash,
                },
            },
        )
