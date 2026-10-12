"""What a program's telemetry settings turn on, and that with none of
them nothing changes."""

import json
import logging
import re
from collections.abc import Iterator

import pytest
from temporalio.contrib.opentelemetry import TracingInterceptor

from bugflow.apps.shared.telemetry import (
    EXCLUDED_URLS,
    client_interceptors,
    configure_logging,
    configure_telemetry,
)


@pytest.fixture
def root() -> Iterator[logging.Logger]:
    """The root logger, put back as it was after the test."""
    logger = logging.getLogger()
    handlers, level = list(logger.handlers), logger.level
    yield logger
    logger.handlers = handlers
    logger.setLevel(level)


def test_with_no_settings_nothing_is_exported_and_logging_is_kept(
    root: logging.Logger,
) -> None:
    before = list(root.handlers)

    assert configure_telemetry("worker", {}) is False
    assert root.handlers == before
    assert client_interceptors({}) == ()


def test_an_endpoint_puts_the_tracing_interceptor_on_the_client() -> None:
    (interceptor,) = client_interceptors(
        {"OTEL_EXPORTER_OTLP_ENDPOINT": "http://otel-collector:4317"}
    )
    assert isinstance(interceptor, TracingInterceptor)


def test_the_contract_format_writes_a_line_as_json(
    root: logging.Logger,
) -> None:
    assert configure_logging({"LOG_FORMAT": "contract"}) is True
    (handler,) = root.handlers
    record = logging.LogRecord(
        "bugflow.test",
        logging.WARNING,
        __file__,
        1,
        "a %s",
        ("delivery",),
        None,
    )

    line = json.loads(handler.format(record))

    assert line["level"] == "warning"
    assert line["msg"] == "a delivery"
    assert line["logger"] == "bugflow.test"
    assert "trace_id" not in line


def test_another_format_leaves_logging_as_it_is(root: logging.Logger) -> None:
    before = list(root.handlers)

    assert configure_logging({"LOG_FORMAT": "text"}) is False
    assert root.handlers == before


@pytest.mark.parametrize("path", ["/healthz", "/api/healthcheck"])
def test_a_healthcheck_is_not_traced(path: str) -> None:
    patterns = EXCLUDED_URLS.split(",")
    assert any(re.search(p, f"http://api:8000{path}") for p in patterns)


def test_a_call_of_substance_is_traced() -> None:
    patterns = EXCLUDED_URLS.split(",")
    assert not any(
        re.search(p, "http://api:8000/api/policy-deployments")
        for p in patterns
    )
