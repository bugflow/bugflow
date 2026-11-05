"""What the editor of a review comment is given, and what it gives
back.

A server's draft of a comment is every reviewer's part, one folded
line for each finding. The editor, whose instructions and examples the
binding holds, writes from it the comment the author reads. The draft
is kept beside what was posted, so what the editor dropped or changed
can be read later.
"""

from dataclasses import dataclass

from bugflow.shared.domain.models.call_record import CallRecord


@dataclass(frozen=True, kw_only=True)
class CommentDraft:
    """The draft the editor is given: the parts of the comment, without
    the markers the server reads, and the pull request's title and
    description for context."""

    text: str
    #: The reviewers whose parts the draft holds, in the draft's order.
    reviewers: tuple[str, ...]
    title: str = ""
    description: str = ""


@dataclass(frozen=True, kw_only=True)
class EditedComment:
    """What the editor wrote, the model that wrote it, and the calls
    made to write it, which the caller records."""

    text: str
    model: str | None = None
    calls: tuple[CallRecord, ...] = ()
