"""The interfaces for asking what a repository is reviewed for.

Two interfaces, because a policy and a process are two things and the
domain's divisions decide the interfaces rather than the storage's.
Whether one adapter keeps both in one table is that adapter's business.

Each answers for one repository and lists what it holds. A declaration
nothing can list has to be worked around before a page can show it.
"""

from typing import Protocol

from bugflow.review.domain.models.review_declaration import (
    DispatchedProcesses,
    JudgedPolicies,
)


class JudgedPoliciesService(Protocol):
    def judged(self, forge: str, repo: str) -> frozenset[str]:
        """Return the policies judged for that repository, empty where
        none.

        Empty is the default and is not a failure to read: a repository
        nobody has decided about is judged on nothing.
        """
        ...

    def declarations(self) -> list[JudgedPolicies]:
        """Return every repository that has declared, by forge and
        name."""
        ...

    def declare(self, declaration: JudgedPolicies) -> None:
        """Replace what that repository is judged for.

        The whole set, not an addition: a caller that meant to remove one
        policy sends the rest, and a caller holding a stale set cannot
        silently turn something back on by adding to it.
        """
        ...


class DispatchedProcessesService(Protocol):
    def dispatched(self, forge: str, repo: str) -> frozenset[str]:
        """Return the processes dispatched for that repository, empty
        where none."""
        ...

    def declarations(self) -> list[DispatchedProcesses]:
        """Return every repository that has declared, by forge and
        name."""
        ...

    def declare(self, declaration: DispatchedProcesses) -> None:
        """Replace what that repository dispatches, as a whole set."""
        ...
