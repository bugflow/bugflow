"""Tests of ``served_by``: asking a LiteLLM proxy which model answers
for each name it publishes."""

from typing import Any

import httpx2
import pytest

from bugflow.work.infrastructure.litellm_roles import (
    ServingUnknownError,
    served_by,
)


def proxy(
    status: int = 200,
    body: Any = None,
    error: Exception | None = None,
) -> httpx2.Client:
    """An HTTP client whose every request gets this answer."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/model/info"
        if error is not None:
            raise error
        if isinstance(body, str):
            return httpx2.Response(status, text=body)
        return httpx2.Response(status, json=body)

    return httpx2.Client(
        base_url="http://proxy.example:4000",
        transport=httpx2.MockTransport(handler),
    )


def deployment(name: str, model: str) -> dict[str, Any]:
    return {"model_name": name, "litellm_params": {"model": model}}


def test_each_name_is_given_with_the_model_behind_it() -> None:
    body = {
        "data": [
            deployment("small", "vendor-a/quick-1"),
            deployment("large", "vendor-b/thorough-2"),
        ]
    }

    assert served_by(proxy(body=body)) == {
        "small": "quick-1",
        "large": "thorough-2",
    }


def test_a_name_with_several_deployments_gives_all_their_models() -> None:
    body = {
        "data": [
            deployment("small", "vendor-b/quick-2"),
            deployment("small", "vendor-a/quick-1"),
            deployment("small", "vendor-c/quick-1"),
        ]
    }

    assert served_by(proxy(body=body)) == {"small": "quick-1, quick-2"}


def test_an_entry_without_a_name_or_a_model_is_left_out() -> None:
    body = {
        "data": [
            {"model_name": "small"},
            {"litellm_params": {"model": "vendor-a/quick-1"}},
            "not an entry",
            deployment("large", "thorough-2"),
        ]
    }

    assert served_by(proxy(body=body)) == {"large": "thorough-2"}


@pytest.mark.parametrize(
    "status,body",
    [
        (404, {"detail": "Not Found"}),
        (200, "not json"),
        (200, ["not", "an", "object"]),
        (200, {"data": "not a list"}),
    ],
)
def test_a_proxy_that_does_not_say_gives_nothing(
    status: int, body: Any
) -> None:
    assert served_by(proxy(status=status, body=body)) == {}


def test_a_proxy_that_answers_with_an_error_is_reported() -> None:
    with pytest.raises(ServingUnknownError, match="answered 500"):
        served_by(proxy(status=500, body={}))


def test_a_proxy_that_cannot_be_reached_is_reported() -> None:
    with pytest.raises(ServingUnknownError, match="no route"):
        served_by(proxy(error=httpx2.ConnectError("no route")))
