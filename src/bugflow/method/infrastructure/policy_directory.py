"""Read a deployment from a directory laid out as a policy repository.

Only the files a server reads are taken: each reviewer's manifest, its
policies and its doctrine, the two files beside the reviewers, and the
words documents under ``glossary/``. A reviewer's policies and doctrine
are in its ``policies`` and ``doctrine`` directories. Each of its skills
carries a copy of both under ``skills/<name>/references/``, and the
copies are not sent. A reviewer laid out before the originals were kept
at its root has the files in one skill's ``references`` directory and
nothing at its root, and that skill's files are sent. A file of any
other name is left out, so a policy repository can hold notes,
calibration cases, scripts and a pipeline without sending them.
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
    "profiles.toml",
    "*/manifest.md",
    "*/reviewer.md",
    "*/policies/*.md",
    "*/doctrine/*.md",
    "*/skills/*/references/policies/*.md",
    "*/skills/*/references/doctrine/*.md",
    "glossary/**/*.md",
    "glossary/**/*.txt",
    "glossary/**/*.org",
)
#: The directories a reviewer keeps its originals in.
ORIGINALS = ("policies", "doctrine")


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
                if not self._is_copy(path)
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

    def _is_copy(self, path: Path) -> bool:
        """Whether the path is a skill's copy of a policy or doctrine
        file: one under ``skills/`` of a reviewer that has a
        ``policies`` or ``doctrine`` directory of its own."""
        parts = path.relative_to(self._directory).parts
        if len(parts) != 6 or parts[0] == "glossary" or parts[1] != "skills":
            return False
        reviewer = self._directory / parts[0]
        return any((reviewer / name).is_dir() for name in ORIGINALS)
