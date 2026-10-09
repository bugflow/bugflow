"""The interface for asking that a repository's corpus be loaded again.

A corpus is the body of documents a repository keeps that the server
tracks. It changes only when a pull request is merged. So after each
merge this context asks for it to be loaded again. Loading it is another
context's work.
"""

from typing import Protocol

from bugflow.shared.domain.values.correlation import Correlation


class CorpusRefreshPort(Protocol):
    def refresh(self, forge: str, repository: str) -> Correlation:
        """Ask for the corpus of ``repository`` (``owner/name``) on
        ``forge`` to be loaded again from its default branch. If a load
        is already running, another is done after it.

        Returns the workflow run that will do it. Raises
        ``EvaluationStartError`` if the request could not be made.
        """
        ...
