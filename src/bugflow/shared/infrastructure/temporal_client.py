"""Where Temporal is, and a client connected to it.

Every program that talks to Temporal reads the same three settings and
connects the same way: the worker, the ingress and the archive host.
This module holds that one reading, so an adapter in any context may
take a ``TemporalSettings`` and connect with it, and the programs read
the settings once.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from urllib.parse import quote

from temporalio.client import Client, Interceptor
from temporalio.contrib.pydantic import pydantic_data_converter

#: The task queue the programs use when ``TEMPORAL_TASK_QUEUE`` is unset.
DEFAULT_TASK_QUEUE = "bugflow"


class TemporalUnavailableError(Exception):
    """Temporal could not be reached."""


@dataclass(frozen=True)
class TemporalSettings:
    """Where Temporal is, and which queue the worker listens on."""

    address: str
    namespace: str
    task_queue: str
    ui_url: str

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str]
    ) -> "TemporalSettings":
        """Read ``TEMPORAL_ADDRESS``, ``TEMPORAL_NAMESPACE``,
        ``TEMPORAL_TASK_QUEUE`` and ``TEMPORAL_UI_URL``, each with a
        default for a server on the same host."""
        return cls(
            address=environ.get("TEMPORAL_ADDRESS") or "localhost:7233",
            namespace=environ.get("TEMPORAL_NAMESPACE") or "default",
            task_queue=environ.get("TEMPORAL_TASK_QUEUE")
            or DEFAULT_TASK_QUEUE,
            ui_url=environ.get("TEMPORAL_UI_URL") or "http://localhost:8080",
        )

    def history_url(self, workflow_id: str, run_id: str) -> str:
        """The address of a run's history in Temporal's own web UI."""
        return (
            f"{self.ui_url}/namespaces/{self.namespace}/workflows/"
            f"{quote(workflow_id, safe='')}/{run_id}/history"
        )


async def connect(
    settings: TemporalSettings, interceptors: Sequence[Interceptor] = ()
) -> Client:
    """Connect to Temporal, or raise ``TemporalUnavailableError``.

    ``interceptors`` are the client's, for a program that traces what it
    starts.
    """
    try:
        return await Client.connect(
            settings.address,
            namespace=settings.namespace,
            data_converter=pydantic_data_converter,
            interceptors=list(interceptors),
        )
    except Exception as exc:
        raise TemporalUnavailableError(
            f"could not reach Temporal at {settings.address}"
        ) from exc
