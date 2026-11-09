"""The editor of a review comment, over the LiteLLM proxy.

The binding's ``pr-comment-editor.md`` gives the instructions and the
class of model, and its examples under ``pr-comment-editor/examples/``
show what a good comment is and what a bad one is. The editor sends
one chat completion: the instructions and the examples as the system
message, and the draft with the pull request's title and description
as the user message. What comes back is the comment, as text.

Every call goes through ``LiteLLMClient`` and is recorded, so what the
editor costs is added up with the judge's calls.
"""

from collections.abc import Mapping
from typing import Any

import httpx2

from bugflow.apps.shared.policies import ReviewersInForce
from bugflow.apps.worker.litellm_judge import (
    DEFAULT_URL,
    MODEL_CLASS_DEFAULTS,
    _error_message,
    model_classes_from_environment,
)
from bugflow.method.domain.models.editor import Editor
from bugflow.review.domain.errors import EditorUnavailableError
from bugflow.review.domain.models.comment_edit import (
    NOTHING_TO_RAISE,
    CommentDraft,
    EditedComment,
)
from bugflow.review.domain.values.delimiting import closing_escaped
from bugflow.shared.domain.services.object_store import ObjectStoreService
from bugflow.shared.infrastructure.null_object_store import NullObjectStore
from bugflow.work.infrastructure.litellm_client import LiteLLMClient

#: The tags the request delimits its parts with, which the texts inside
#: them may not close.
EDIT_TAGS = ("example", "why", "comment", "title", "description", "draft")

#: What the server asks beyond the binding's instructions: the shape of
#: the answer, which is the server's contract with the model and not
#: the binding's taste.
ANSWER = (
    "Answer with the comment alone, in Markdown, with nothing before it "
    "and nothing after it. If nothing in the draft is worth the author's "
    "reading, and the draft reports nothing the author fixed, answer "
    f"`{NOTHING_TO_RAISE}` alone, and no comment is posted."
)


def _text(value: str) -> str:
    return closing_escaped(value, *EDIT_TAGS)


def render_examples(editor: Editor) -> str:
    """The editor's examples as the model is shown them, in path order,
    each with its kind and its why."""
    return "\n\n".join(
        f'<example kind="{one.kind}">\n'
        f"<why>{_text(one.why)}</why>\n"
        f"<comment>\n{_text(one.text)}\n</comment>\n"
        "</example>"
        for one in editor.examples
    )


def render_edit_request(
    editor: Editor,
    draft: CommentDraft,
    model: str,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Build the chat completion the editor sends: the prompt the model
    sees."""
    examples = render_examples(editor)
    system = editor.instructions
    if examples:
        system += f"\n\n{examples}"
    system += f"\n\n{ANSWER}"
    return {
        "model": model,
        "temperature": temperature or 0,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"<title>{_text(draft.title)}</title>\n"
                    f"<description>\n{_text(draft.description)}\n"
                    "</description>\n"
                    f"<draft>\n{_text(draft.text)}\n</draft>"
                ),
            },
        ],
    }


def _content(payload: dict[str, Any]) -> str:
    """The text of the first choice, or empty."""
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    return content if isinstance(content, str) else ""


class LiteLLMCommentEditor:
    """Implements ``CommentEditorService`` over the proxy."""

    def __init__(
        self,
        url: str,
        key: str,
        editor: Editor,
        model_classes: Mapping[str, str] | None = None,
        transport: httpx2.BaseTransport | None = None,
        objects: ObjectStoreService | None = None,
        temperature: float = 0.0,
    ) -> None:
        """Build the editor the binding describes. ``model_classes``
        gives each class's model, as the judge's are given.

        Raises ``ValueError`` without a key, or for an editor naming a
        class of model nothing defines.
        """
        if not key:
            raise ValueError("a LiteLLM key is required")
        models = dict(model_classes or MODEL_CLASS_DEFAULTS)
        if editor.model_class not in models:
            raise ValueError(f"no class of model named {editor.model_class}")
        self._editor = editor
        self._model = models[editor.model_class]
        self._temperature = temperature
        self._url = url
        self._client = httpx2.Client(
            base_url=url,
            headers={"Authorization": f"Bearer {key}"},
            timeout=120.0,
            transport=transport,
        )
        self._calls = LiteLLMClient(self._client, objects or NullObjectStore())

    @property
    def model(self) -> str:
        """The model the editor asks for: its class's."""
        return self._model

    def edit(self, draft: CommentDraft) -> EditedComment:
        request = render_edit_request(
            self._editor, draft, self._model, self._temperature
        )
        result = self._calls.complete(request, purpose="edit")
        record = result.record
        if result.error is not None:  # includes timeouts
            raise EditorUnavailableError(
                f"could not reach the editor at {self._url}: {result.error}",
                calls=(record,),
            )
        status = result.status_code or 0
        if status >= 400:
            raise EditorUnavailableError(
                f"the editor answered {status}: {_error_message(result)}",
                calls=(record,),
            )
        if result.payload is None:
            raise EditorUnavailableError(
                f"the editor answered {status} with no JSON body",
                calls=(record,),
            )
        text = _content(result.payload).strip()
        if not text:
            raise EditorUnavailableError(
                "the editor answered nothing", calls=(record,)
            )
        return EditedComment(
            text=text,
            model=record.answered_model or self._model,
            calls=(record,),
        )


def comment_editor_from_environment(
    environ: Mapping[str, str],
    reviewers: ReviewersInForce | None,
    objects: ObjectStoreService | None = None,
) -> LiteLLMCommentEditor | None:
    """Build the editor of the deployment in force, or None where the
    binding carries none or there is no key to call the proxy with.

    Settings: ``LITELLM_MASTER_KEY`` is the key and ``JUDGE_URL`` the
    proxy's address, as for the judge. The classes' models are read by
    ``model_classes_from_environment``.
    """
    key = environ.get("LITELLM_MASTER_KEY")
    if not key or reviewers is None or reviewers.editor is None:
        return None
    return LiteLLMCommentEditor(
        url=environ.get("JUDGE_URL") or DEFAULT_URL,
        key=key,
        editor=reviewers.editor,
        model_classes=model_classes_from_environment(environ),
        objects=objects,
    )
