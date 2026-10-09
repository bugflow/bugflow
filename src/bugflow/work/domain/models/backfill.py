"""What a backfill needs to know about a repository and its closed pull
requests.

A backfill reviews a repository's old pull requests. These types are
this context's own, and hold only what a backfill uses.
"""

import re
from dataclasses import dataclass
from typing import Literal, Self

from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

_WATCHED = re.compile(
    r"^(?:(?P<forge>github|forgejo):)?(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)$"
)


@dataclass(frozen=True, kw_only=True)
class WatchedRepository:
    """A repository to backfill, and which kind of forge it is on."""

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


@dataclass(frozen=True, kw_only=True)
class BackfillCandidate:
    """One closed pull request: which one, and its last commit."""

    ref: PullRequestRef
    head_sha: str


@dataclass(frozen=True, kw_only=True)
class BackfillPage:
    """One page of a repository's closed pull requests, oldest first."""

    pulls: tuple[BackfillCandidate, ...]
    #: True if this is the last page.
    last: bool
