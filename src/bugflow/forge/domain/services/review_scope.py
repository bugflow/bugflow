"""The interface for finding out which policies apply to a repository.

Each observation records the review scope: the policies the server could
apply and the ones the repository asked for. Other contexts know those
two things. This context only needs them as two lists of names, so it
declares this interface and an application supplies the answer.

The scope is recorded at the time because a repository's choice can
change, and nothing else keeps a history of what it was.
"""

from typing import Protocol

from bugflow.forge.domain.values.review_scope import ReviewScope


class ReviewScopeService(Protocol):
    def scope_for(self, forge: str, repo: str) -> ReviewScope:
        """The review scope for the repository on that forge."""
        ...
