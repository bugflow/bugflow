"""The files one commit of a policy repository sent to a server.

A deployment holds each reviewer's manifest, policies and doctrine, and
the files beside the reviewers that say when reviews run and what each
repository is reviewed for. It is kept whole and never edited, so the
text a finding was raised under can be read later.

A deployment has two names. The repository and the commit are what the
sender said it is, and a server cannot check them. The content hash is
computed from the files, so two deployments with one hash hold the same
text whatever they were called.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath

from bugflow.method.domain.errors import PolicyDeploymentError


@dataclass(frozen=True, kw_only=True)
class DeployedFile:
    """One file of a deployment: its path inside the deployment, and its
    text."""

    path: str
    text: str


def _checked(path: str) -> str:
    """The path, if it is inside the deployment.

    A path is relative, with forward slashes and no step upward. A file
    then has the same path whoever sent it, and no path names anything
    outside the deployment.
    """
    parts = PurePosixPath(path).parts
    if (
        not path
        or path.startswith("/")
        or "\\" in path
        or ".." in parts
        or str(PurePosixPath(path)) != path
    ):
        raise PolicyDeploymentError(
            f"{path!r} is not a path inside the deployment"
        )
    return path


@dataclass(frozen=True, kw_only=True)
class PolicyDeployment:
    """The files one commit of a policy repository deployed, in path
    order."""

    repository: str
    commit: str
    files: tuple[DeployedFile, ...]

    def __post_init__(self) -> None:
        if not self.repository or not self.commit:
            raise PolicyDeploymentError(
                "a deployment names its repository and its commit"
            )
        paths = [_checked(one.path) for one in self.files]
        twice = sorted({path for path in paths if paths.count(path) > 1})
        if twice:
            raise PolicyDeploymentError(
                f"{', '.join(twice)} sent more than once"
            )
        object.__setattr__(
            self, "files", tuple(sorted(self.files, key=lambda f: f.path))
        )

    @property
    def content_hash(self) -> str:
        """A hash of every path and text, in path order.

        The repository and the commit are not hashed. They are names the
        sender chose.
        """
        canonical = json.dumps(
            [[one.path, one.text] for one in self.files], ensure_ascii=False
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    def text_of(self, path: str) -> str | None:
        """The text of the file at that path, or None if there is none."""
        for one in self.files:
            if one.path == path:
                return one.text
        return None


@dataclass(frozen=True, kw_only=True)
class PutInForce:
    """One time a deployment was put in force: its names, and when."""

    repository: str
    commit: str
    content_hash: str
    at: datetime
