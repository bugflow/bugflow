"""The acknowledgement: what a handler answers when it is handed
something.

A use case sometimes notices that something has happened and hands it to
a handler, without knowing what the handler will do: start a workflow,
tell a running one, or nothing. So the handler's answer is not the result
of any work. It only says whether the handler will act.

The three answers borrow radio words:

- "wilco": will comply. The handler will act.
- "unable": it will not.
- "roger": received, with no promise either way.
"""

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class Acknowledgement:
    #: True for wilco, False for unable, None for roger.
    will_comply: bool | None = None
    #: Anything the handler wants to say about its answer.
    info: tuple[str, ...] = ()

    @classmethod
    def wilco(cls, *info: str) -> "Acknowledgement":
        return cls(will_comply=True, info=info)

    @classmethod
    def unable(cls, *info: str) -> "Acknowledgement":
        return cls(will_comply=False, info=info)

    @classmethod
    def roger(cls, *info: str) -> "Acknowledgement":
        return cls(will_comply=None, info=info)
