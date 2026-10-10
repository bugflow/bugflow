"""The request and response of ``DeployPoliciesUseCase``.

The body is also what a policy repository's pipeline posts to an API.
"""

from pydantic import BaseModel, ConfigDict, Field

from bugflow.method.domain.values.server_answer import Outcome


class PolicyFile(BaseModel):
    """One file of a deployment: its path inside the deployment, and its
    text."""

    model_config = ConfigDict(frozen=True)

    path: str
    text: str


class DeployPoliciesBody(BaseModel):
    """What a sender chooses: the content, and the names it goes by."""

    model_config = ConfigDict(frozen=True)

    repository: str = Field(
        description="the policy repository the files are from, as owner/name"
    )
    commit: str = Field(
        description="the commit of that repository the files are from"
    )
    files: tuple[PolicyFile, ...] = Field(
        description="each reviewer's reviewer.md, policies/*.md and "
        "doctrine/*.md, and the files beside the reviewers"
    )
    check_only: bool = Field(
        default=False,
        description="parse the files and answer, storing nothing",
    )


class DeployPoliciesRequest(DeployPoliciesBody):
    """The body, and who sent it, which the sender does not choose."""

    #: The token's subject and client for a call through an API, or a
    #: word saying the command was run on the host.
    sent_by: str


class InForce(BaseModel):
    """The deployment in force, by its names."""

    model_config = ConfigDict(frozen=True)

    repository: str
    commit: str
    content_hash: str


class DeployPoliciesResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: Outcome
    #: The hash of the files that were sent.
    content_hash: str
    #: The deployment in force after the call, or None on a server that
    #: has never been sent one, after a check.
    in_force: InForce | None
