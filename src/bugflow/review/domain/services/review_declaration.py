"""The interfaces for asking what a repository is reviewed for.

Two interfaces, because a policy and a process are two things and the
domain's divisions decide the interfaces rather than the storage's. Both
are answered from each gnome's setting on the repository (ADR 008).
"""

from typing import Protocol


class JudgedPoliciesService(Protocol):
    def judged(self, forge: str, repo: str) -> frozenset[str]:
        """Return the policies judged for that repository, empty where
        none.

        Empty is the default and is not a failure to read: a repository
        no gnome is set on is judged on nothing.
        """
        ...


class DispatchedProcessesService(Protocol):
    def dispatched(self, forge: str, repo: str) -> frozenset[str]:
        """Return the processes dispatched for that repository, empty
        where none."""
        ...
