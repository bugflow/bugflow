"""The interface to the editor of a review comment."""

from typing import Protocol

from bugflow.review.domain.models.comment_edit import (
    CommentDraft,
    EditedComment,
)


class CommentEditorService(Protocol):
    def edit(self, draft: CommentDraft) -> EditedComment:
        """Write the comment from the draft.

        Raises ``EditorUnavailableError`` if the editor refuses or
        cannot answer. The caller posts the draft as it is.
        """
        ...
