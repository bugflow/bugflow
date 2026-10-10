"""The request and response of ``SendPoliciesUseCase``."""

from pydantic import BaseModel, ConfigDict

from bugflow.method.domain.values.server_answer import Outcome


class SendPoliciesRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    #: The policy repository the files are from, as owner/name.
    repository: str
    #: The commit of that repository the files are from.
    commit: str
    #: True to have the server parse the files and store nothing.
    check_only: bool = False


class DeploymentInForce(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: str
    commit: str
    content_hash: str


class SendPoliciesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Outcome
    #: How many files were sent.
    files: int
    #: The hash the server computed from them.
    content_hash: str
    #: The deployment in force after the call, or None if the server has
    #: never been sent one.
    in_force: DeploymentInForce | None
