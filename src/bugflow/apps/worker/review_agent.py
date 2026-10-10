"""The managed agent that reviews, built from this worker's settings."""

from collections.abc import Mapping

from anthropic import Anthropic

from bugflow.shared.domain.services.object_store import ObjectStoreService
from bugflow.work.infrastructure.managed_agent import (
    ManagedAgent,
    ManagedAgentSettings,
)

#: The name of the agent object and of the environment on the platform.
AGENT_NAME = "bugflow-review"

#: Where repositories are mounted from when ``FORGE_CLONE_URL`` is not
#: given.
DEFAULT_CLONE_URL = "https://github.com"


def review_agent_settings(environ: Mapping[str, str]) -> ManagedAgentSettings:
    """Read what this worker chooses about the managed agent.

    Settings: ``REVIEW_AGENT_MODEL`` is the model, by the platform's
    name for it. ``FORGE_CLONE_URL`` is the address repositories are
    mounted from.

    Raises ``ValueError`` if no model is named. No model is a default:
    which model reviews is the deployment's choice.
    """
    model = environ.get("REVIEW_AGENT_MODEL", "")
    if not model:
        raise ValueError(
            "REVIEW_AGENT_MODEL is required: it names the model the "
            "managed agent reviews with"
        )
    return ManagedAgentSettings(
        name=AGENT_NAME,
        model=model,
        clone_url=environ.get("FORGE_CLONE_URL") or DEFAULT_CLONE_URL,
    )


def managed_agent_from_environment(
    environ: Mapping[str, str],
    objects: ObjectStoreService | None = None,
) -> ManagedAgent | None:
    """Build the managed runner, or return None if its credentials are
    not given.

    Settings: ``REVIEW_ANTHROPIC_API_KEY`` is the key sessions are
    created with. It is separate from the key the judge is called with,
    so that a spend limit on one does not cap the other and either can
    be revoked alone. ``REVIEW_REPOSITORY_TOKEN`` is the token the
    platform's git proxy fetches the repository with. It is not the
    forge's token: anything in the container can act through the proxy
    with this token's permissions, so it must only be able to read.
    ``REVIEW_COMPLETION_WEBHOOK``, if given, says the platform is set
    up to tell this server when a session stops. The model and the
    clone address are read by ``review_agent_settings``.

    ``objects`` is where a run's workings are stored, if anywhere.

    Raises ``ValueError`` if the credentials are given and no model is
    named.
    """
    key = environ.get("REVIEW_ANTHROPIC_API_KEY", "")
    token = environ.get("REVIEW_REPOSITORY_TOKEN", "")
    if not (key and token):
        return None
    return ManagedAgent(
        client=Anthropic(api_key=key),
        repository_token=token,
        settings=review_agent_settings(environ),
        notified=bool(environ.get("REVIEW_COMPLETION_WEBHOOK", "")),
        objects=objects,
    )
