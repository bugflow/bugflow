"""The forges a worker reads and writes, chosen for each pull request by
the forge its reference names."""

from collections.abc import Mapping

from bugflow.apps.shared.forges import forge_token, forgejo_settings
from bugflow.apps.worker.conversation import ConversingForge
from bugflow.forge.domain.errors import ForgeRejectedError
from bugflow.forge.domain.models.pull_request import PullRequestSnapshot
from bugflow.forge.domain.services.forge import CommitState
from bugflow.forge.domain.values.conversation import PullRequestState, Reaction
from bugflow.forge.infrastructure.forgejo import ForgejoForge
from bugflow.forge.infrastructure.github import GitHubForge
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef


class MissingForge:
    """A stand-in for a forge that is not set up.

    The worker still starts, and each evaluation of a pull request on
    that forge fails with this reason and not with an authentication
    error from the forge.
    """

    def __init__(self, reason: str) -> None:
        self._reason = reason

    def fetch_snapshot(self, ref: PullRequestRef) -> PullRequestSnapshot:
        raise ForgeRejectedError(self._reason)

    def is_open(self, ref: PullRequestRef) -> bool:
        raise ForgeRejectedError(self._reason)

    def reactions(
        self, ref: PullRequestRef, comment_id: int
    ) -> tuple[Reaction, ...]:
        raise ForgeRejectedError(self._reason)

    def state(self, ref: PullRequestRef) -> PullRequestState:
        raise ForgeRejectedError(self._reason)

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        raise ForgeRejectedError(self._reason)

    def set_labels(
        self,
        ref: PullRequestRef,
        add: frozenset[str],
        remove: frozenset[str],
    ) -> None:
        raise ForgeRejectedError(self._reason)

    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: CommitState,
        description: str,
    ) -> None:
        raise ForgeRejectedError(self._reason)


class ForgeByReference:
    """Each pull request's own forge, chosen by the forge its reference
    names."""

    def __init__(self, forges: Mapping[str, ConversingForge]) -> None:
        self._forges = forges

    def forge_for(self, ref: PullRequestRef) -> ConversingForge:
        return self._forges[ref.forge]

    def reactions(
        self, ref: PullRequestRef, comment_id: int
    ) -> tuple[Reaction, ...]:
        return self.forge_for(ref).reactions(ref, comment_id)

    def state(self, ref: PullRequestRef) -> PullRequestState:
        return self.forge_for(ref).state(ref)

    def fetch_snapshot(self, ref: PullRequestRef) -> PullRequestSnapshot:
        return self.forge_for(ref).fetch_snapshot(ref)

    def is_open(self, ref: PullRequestRef) -> bool:
        return self.forge_for(ref).is_open(ref)

    def add_comment(self, ref: PullRequestRef, marker: str, body: str) -> int:
        return self.forge_for(ref).add_comment(ref, marker, body)

    def set_labels(
        self,
        ref: PullRequestRef,
        add: frozenset[str],
        remove: frozenset[str],
    ) -> None:
        self.forge_for(ref).set_labels(ref, add, remove)

    def set_commit_status(
        self,
        ref: PullRequestRef,
        sha: str,
        context: str,
        state: CommitState,
        description: str,
    ) -> None:
        self.forge_for(ref).set_commit_status(
            ref, sha, context, state, description
        )


def forge_from_environment(environ: Mapping[str, str]) -> ForgeByReference:
    """Build the forges from the settings ``apps/shared/forges.py``
    reads. A forge whose settings are not given is a ``MissingForge``."""
    token = forge_token(environ)
    forgejo = forgejo_settings(environ)
    return ForgeByReference(
        {
            "github": GitHubForge(token)
            if token
            else MissingForge("no forge token configured; set FORGE_TOKEN"),
            "forgejo": ForgejoForge(*forgejo)
            if forgejo
            else MissingForge(
                "no Forgejo configured; set FORGEJO_URL and FORGEJO_TOKEN"
            ),
        }
    )
