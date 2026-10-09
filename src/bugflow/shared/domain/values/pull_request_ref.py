"""The reference to a pull request: which forge, which repository, which
number.

A forge is a service that hosts git repositories and pull requests, such
as GitHub or Forgejo. Every context that reads or acts on a pull request
identifies it by this reference.
"""

import re
from dataclasses import dataclass
from typing import Literal, Self

_SHORT_REF = re.compile(
    r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$"
)
_URL_REF = re.compile(
    r"^https?://[^/]+/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)"
    r"/pulls?/(?P<number>\d+)/?$"
)


@dataclass(frozen=True, kw_only=True)
class PullRequestRef:
    #: Which kind of forge the pull request is on.
    forge: Literal["github", "forgejo"] = "github"
    owner: str
    repo: str
    number: int

    @classmethod
    def parse(cls, text: str) -> Self:
        """Read a reference from ``owner/repo#number`` or from a pull
        request's URL. Raises ``ValueError`` for anything else.

        GitHub URLs contain ``/pull/`` and Forgejo URLs ``/pulls/``; both
        are accepted. The result's ``forge`` is the default either way,
        since a URL's host does not say which kind of forge it is.
        """
        for pattern in (_SHORT_REF, _URL_REF):
            match = pattern.match(text.strip())
            if match:
                return cls(
                    owner=match["owner"],
                    repo=match["repo"],
                    number=int(match["number"]),
                )
        raise ValueError(
            f"not a pull request reference: {text!r}; "
            "expected owner/repo#number or a pull request URL"
        )

    def __str__(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"
