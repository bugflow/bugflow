"""Turn a webhook event from Anthropic's Managed Agents into a
completion.

The platform sends a webhook for many kinds of event. Only an event
that says a session has stopped is a completion. The others are
ignored.
"""

from typing import Any

from bugflow.work.domain.models.completion import Completion
from bugflow.work.infrastructure.managed_agent import RUNNER

# The event types that say a session has stopped: it went idle, or it
# was terminated. Why it stopped is read later, when the run is
# collected.
_STOPPED = frozenset({"session.status_idled", "session.status_terminated"})


def completion_from_managed_agent(event: Any) -> Completion | None:
    """Return the completion that a webhook event stands for, or None.

    ``event`` is the event after the SDK has checked its signature and
    parsed it. Returns None for an event of another type, and for one
    that gives no session id.
    """
    data = event.data
    if getattr(data, "type", "") not in _STOPPED:
        return None
    session_id = str(getattr(data, "id", "") or "")
    if not session_id:
        return None
    return Completion(runner=RUNNER, remote_id=session_id)
