"""The exchange with a judge's model, and what identifies a judgement."""

from dataclasses import dataclass
from typing import Any

from bugflow.shared.domain.values.digest import content_hash


@dataclass(frozen=True, kw_only=True)
class JudgeExchange:
    """One request sent to the judge's model, and its response."""

    request: dict[str, Any]
    response: dict[str, Any]

    @property
    def exchange_id(self) -> str:
        """A hash of the request and the response together. The exchange
        is stored under this id."""
        return content_hash(
            {"request": self.request, "response": self.response}
        )


@dataclass(frozen=True, kw_only=True)
class JudgeIdentity:
    """What a judged finding came from. It is enough to run the same
    judgement again."""

    #: The model that answered. If the provider fell back to another
    #: model, this is that one, not the one asked for.
    model: str
    #: A hash of the judge's model name and the source of its adapter.
    fingerprint: str
    #: A hash of the request as it was sent, or None if there was none.
    prompt_hash: str | None
    #: A hash of the content of the submission that was judged.
    input_hash: str
    #: The id of the stored exchange, or None if it was not stored.
    exchange_id: str | None


@dataclass(frozen=True, kw_only=True)
class JudgeReproduction:
    """A stored judgement that was run again, with both results."""

    #: The id of the stored exchange that was run again.
    exchange_id: str
    #: The model that answered the second time.
    model: str
    #: What the stored response found, and what the new one found. Each
    #: is a sorted list of lines of the form "clause: quotation".
    archived: tuple[str, ...]
    replayed: tuple[str, ...]
    #: The new exchange, to be stored.
    replay: JudgeExchange

    @property
    def matches(self) -> bool:
        """Whether the model found the same things both times."""
        return self.archived == self.replayed
