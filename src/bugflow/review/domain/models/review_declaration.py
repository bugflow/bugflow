"""What a repository is reviewed for.

Two declarations, because a policy and a process are two things at two
levels and the domain says so rather than the table. A policy is judged
once an evaluation and belongs to a reviewer's corpus; a process is what
a pace layer holds, and a process runs policies.

Both belong to the deployment. A repository declaring its own review
could switch it off; a record in the deployment's database, edited
through the deployment's page, is still the deployment's.

A repository with no declaration is reviewed for nothing. The absent
case is the common one and it costs nothing, which inverts a default
under which a repository nobody had decided about was judged on every
policy and dispatched every reviewer.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class JudgedPolicies:
    """The policies judged for one repository.

    Empty is a real answer and the default: nothing is judged until
    something says so.
    """

    forge: str
    repo: str
    policies: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class DispatchedProcesses:
    """The processes dispatched for one repository.

    A name the topology declares. A process named here that the topology
    does not hold runs nowhere, as a reviewer no layer names does: this
    says which of the method's loops apply to a repository, and never
    what the loops are.
    """

    forge: str
    repo: str
    processes: tuple[str, ...] = ()
