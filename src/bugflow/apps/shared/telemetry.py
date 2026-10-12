"""Traces sent over OTLP, and log lines written as JSON.

A hosting platform that collects telemetry asks two things of a
program. It sends its traces to the OTLP endpoint
``OTEL_EXPORTER_OTLP_ENDPOINT`` names. It writes its log lines to stdout
as JSON carrying ``level`` and ``msg``, and ``trace_id`` and ``span_id``
inside a trace, when ``LOG_FORMAT`` is ``contract``. With neither set,
nothing here changes what a program does.

What is traced: the database, through psycopg and SQLAlchemy; the
ingress's and the API's requests; every outbound call made with httpx2,
which covers the forge and the model proxy; and each workflow and
activity, through Temporal's tracing interceptor on the client, which
carries a delivery's trace into the workflow it starts.
"""

import logging
from collections.abc import Mapping
from typing import Any

#: The setting tracing turns on. Unset, nothing is exported.
ENDPOINT = "OTEL_EXPORTER_OTLP_ENDPOINT"

#: The setting that, as ``contract``, writes log lines as JSON.
LOG_FORMAT = "LOG_FORMAT"

#: Requests that are never traced: a container's healthcheck, which is
#: most of a quiet server's traffic. Matched as a regular expression
#: against the URL.
EXCLUDED_URLS = "healthz"


def enabled(environ: Mapping[str, str]) -> bool:
    """Whether traces are exported."""
    return bool(environ.get(ENDPOINT))


def configure_logging(environ: Mapping[str, str]) -> bool:
    """Write the root logger's lines to stdout as JSON, when
    ``LOG_FORMAT`` is ``contract``, and say whether it did.

    Otherwise logging is left as it is, so a test or a developer keeps
    the handlers they set.
    """
    if environ.get(LOG_FORMAT) != "contract":
        return False
    from telemetry_juice import ContractFormatter

    handler = logging.StreamHandler()
    handler.setFormatter(ContractFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    return True


def configure_telemetry(service: str, environ: Mapping[str, str]) -> bool:
    """Set up logging, and start exporting traces as ``service`` when an
    endpoint is set. Say whether traces are exported.

    ``service`` names the program, such as ``worker``. The platform's
    collector adds which server and which environment it runs in.
    """
    configure_logging(environ)
    if not enabled(environ):
        return False
    from telemetry_juice import TelemetryConfig, configure
    from telemetry_juice.integrations.clients import (
        instrument_psycopg,
        instrument_sqlalchemy,
    )
    from telemetry_juice.integrations.httpx2 import instrument_httpx2

    configure(
        TelemetryConfig.from_env(
            service,
            endpoint=environ[ENDPOINT],
            namespace=environ.get("SOLUTION") or None,
            environment=environ.get("ENVIRONMENT") or None,
        )
    )
    instrument_psycopg()
    instrument_sqlalchemy()
    instrument_httpx2()
    return True


def instrument_app(app: Any, environ: Mapping[str, str]) -> None:
    """Trace a FastAPI application's requests, when traces are
    exported."""
    if not enabled(environ):
        return
    from telemetry_juice.integrations.asgi import instrument_fastapi

    instrument_fastapi(app, excluded_urls=EXCLUDED_URLS)


def client_interceptors(environ: Mapping[str, str]) -> tuple[Any, ...]:
    """The interceptors a Temporal client is connected with: Temporal's
    tracing interceptor when traces are exported, and none otherwise.

    A worker built from the client takes the client's interceptors, so
    a worker given the interceptor as well would trace each workflow
    twice.
    """
    if not enabled(environ):
        return ()
    from telemetry_juice.integrations.temporal import TracingInterceptor

    return (TracingInterceptor(),)
