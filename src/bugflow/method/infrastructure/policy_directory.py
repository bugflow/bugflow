"""Read a deployment from a directory laid out as a policy repository.

Only the files a server reads are taken: each reviewer's manifest, its
policies and its doctrine, and the two files beside the reviewers. A
file of any other name is left out, so a policy repository can hold
notes, calibration cases and a pipeline without sending them.
"""

from pathlib import Path

from bugflow.method.domain.models.policy_deployment import (
    DeployedFile,
    PolicyDeployment,
)

#: The files of a deployment, as patterns from the top of the directory.
PATTERNS = (
    "pace-layers.toml",
    "declarations.toml",
    "*/reviewer.md",
    "*/policies/*.md",
    "*/doctrine/*.md",
)


class PolicyDirectory:
    """Implements ``PolicyFilesService`` over one directory."""

    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def read(self, repository: str, commit: str) -> PolicyDeployment:
        paths = sorted(
            {
                path
                for pattern in PATTERNS
                for path in self._directory.glob(pattern)
            }
        )
        return PolicyDeployment(
            repository=repository,
            commit=commit,
            files=tuple(
                DeployedFile(
                    path=path.relative_to(self._directory).as_posix(),
                    text=path.read_text(),
                )
                for path in paths
                if path.is_file()
            ),
        )
