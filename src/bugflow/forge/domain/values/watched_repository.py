"""A repository the poller watches."""

import re
from dataclasses import dataclass
from typing import Literal, Self

_WATCHED = re.compile(
    r"^(?:(?P<forge>github|forgejo):)?(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)$"
)


@dataclass(frozen=True, kw_only=True)
class WatchedRepository:
    """A repository, and which kind of forge it is on."""

    forge: Literal["github", "forgejo"] = "github"
    owner: str
    repo: str

    @classmethod
    def parse(cls, text: str) -> Self:
        """Read ``owner/repo`` for a repository on GitHub, or
        ``forgejo:owner/repo`` for one on Forgejo. Raises ``ValueError``
        for anything else."""
        match = _WATCHED.match(text.strip())
        if match is None:
            raise ValueError(
                f"{text!r} is not owner/repo or forgejo:owner/repo"
            )
        named = match["forge"] or "github"
        return cls(
            forge="forgejo" if named == "forgejo" else "github",
            owner=match["owner"],
            repo=match["repo"],
        )

    def __str__(self) -> str:
        prefix = "" if self.forge == "github" else f"{self.forge}:"
        return f"{prefix}{self.owner}/{self.repo}"
