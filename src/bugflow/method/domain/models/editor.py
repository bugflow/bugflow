"""The editor a binding may carry: the instructions a model is given to
write a review comment from a draft, and the examples that show it what
a good comment is and what a bad one is.

A server's draft is one folded line for each finding, every finding at
the same weight. The editor writes what a reviewer would have written:
the few things that matter, in order, in plain words. The instructions
are the binding's, because one editor speaks for every reviewer on a
server, and the examples are the editor's cases: each is a comment and
one sentence on why it is good or bad.
"""

from dataclasses import dataclass
from typing import Literal

from bugflow.method.domain.errors import PolicyDeploymentError

#: The classes of model a binding may ask for, as a policy's
#: ``model_class`` names them.
MODEL_CLASSES = ("small", "medium", "large")
#: What an example shows: a comment to write like, or one not to.
EXAMPLE_KINDS = ("good", "bad")

ExampleKind = Literal["good", "bad"]


@dataclass(frozen=True, kw_only=True)
class EditorExample:
    """One example comment, with why it is good or bad."""

    #: The example's file name without its suffix, ``good-01-brief``.
    name: str
    kind: ExampleKind
    #: One sentence on what the example shows.
    why: str
    #: The comment, as it was or would be posted.
    text: str

    def __post_init__(self) -> None:
        if self.kind not in EXAMPLE_KINDS:
            raise PolicyDeploymentError(
                f"{self.name}: an example is good or bad, not {self.kind}"
            )
        if not self.why.strip():
            raise PolicyDeploymentError(f"{self.name}: no why")
        if not self.text.strip():
            raise PolicyDeploymentError(f"{self.name}: no comment")


@dataclass(frozen=True, kw_only=True)
class Editor:
    """The editor of a binding: its instructions, the class of model
    that follows them, and its examples in path order."""

    model_class: str
    instructions: str
    examples: tuple[EditorExample, ...] = ()

    def __post_init__(self) -> None:
        if self.model_class not in MODEL_CLASSES:
            raise PolicyDeploymentError(
                f"an editor's model class is one of "
                f"{', '.join(MODEL_CLASSES)}, not {self.model_class}"
            )
        if not self.instructions.strip():
            raise PolicyDeploymentError("an editor has instructions")

    def of_kind(self, kind: ExampleKind) -> tuple[EditorExample, ...]:
        """The examples of one kind, in path order."""
        return tuple(one for one in self.examples if one.kind == kind)
