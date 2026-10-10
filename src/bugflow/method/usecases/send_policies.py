"""Use case: send a policy repository's files to a server.

This is what a policy repository's pipeline does. On a pull request it
sends the files to be checked, and on a merge it sends them to be put in
force. Sending the deployment already in force changes nothing, so a
pipeline may send it again.
"""

from bugflow.method.domain.services.policy_files import PolicyFilesService
from bugflow.method.domain.services.policy_server import PolicyServerService
from bugflow.method.dtos.send_policies import (
    DeploymentInForce,
    SendPoliciesRequest,
    SendPoliciesResponse,
)


class SendPoliciesUseCase:
    """Takes a repository, a commit and whether to check only. Returns
    what the server did and what it has in force afterwards.

    Raises ``PolicyDeploymentError`` if the files are not a deployment,
    ``PoliciesRefusedError`` if the server refuses them, and
    ``PolicyServerError`` if they could not be sent.
    """

    def __init__(
        self, files: PolicyFilesService, server: PolicyServerService
    ) -> None:
        self._files = files
        self._server = server

    def execute(self, request: SendPoliciesRequest) -> SendPoliciesResponse:
        deployment = self._files.read(request.repository, request.commit)
        answer = self._server.send(deployment, request.check_only)
        in_force = answer.in_force
        return SendPoliciesResponse(
            outcome=answer.outcome,
            files=len(deployment.files),
            content_hash=answer.content_hash,
            in_force=DeploymentInForce(
                repository=in_force.repository,
                commit=in_force.commit,
                content_hash=in_force.content_hash,
            )
            if in_force
            else None,
        )
