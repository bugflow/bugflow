"""Tests of ``LiteLLMClient``: what is recorded about a call to a model,
and which files are stored for it.

The proxy is a stand-in that gives the same answer to every request.
"""

import gzip
import json
from typing import Any

import httpx2

from bugflow.shared.domain.errors import ObjectStoreError
from bugflow.shared.infrastructure.in_memory_object_store import (
    InMemoryObjectStore,
)
from bugflow.work.infrastructure.litellm_client import (
    ARCHIVE_HEADER,
    LiteLLMClient,
)

CALL_ID = "0f6d2a34-5b1c-4e7a-9c8d-1a2b3c4d5e6f"

# The response headers a LiteLLM proxy sends that the client reads.
HEADERS = {
    "x-litellm-call-id": CALL_ID,
    "x-litellm-model-id": "0123456789abcdef",
    "x-litellm-model-group": "small",
    "x-litellm-model-api-base": "https://models.example",
    "x-litellm-version": "1.100.1",
    "x-litellm-response-cost": "6e-07",
    "x-litellm-response-cost-input": "6e-07",
    "x-litellm-response-cost-output": "0.0",
    "x-litellm-response-duration-ms": "868.981",
    "x-litellm-overhead-duration-ms": "4.891",
    "x-litellm-attempted-retries": "0",
    "x-litellm-attempted-fallbacks": "0",
}

USAGE: dict[str, Any] = {
    "prompt_tokens": 8106,
    "completion_tokens": 98,
    "total_tokens": 8204,
    "prompt_tokens_details": {"cached_tokens": 3934},
    "completion_tokens_details": {"reasoning_tokens": 60},
}

BODY: dict[str, Any] = {
    "id": "chatcmpl-1",
    "model": "quick-1",
    "choices": [
        {
            "message": {"role": "assistant", "content": "{}"},
            "finish_reason": "stop",
        }
    ],
    "usage": USAGE,
}

REQUEST = {
    "model": "small",
    "messages": [{"role": "user", "content": "hello"}],
}


class NoStore(InMemoryObjectStore):
    """Stands for an application with no object store set up."""

    @property
    def configured(self) -> bool:
        return False


class RefusingStore(InMemoryObjectStore):
    """A store that cannot be written to."""

    def put(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/json",
        content_encoding: str | None = "gzip",
    ) -> None:
        raise ObjectStoreError("the bucket refused the write")


class Proxy:
    """Stands in for the proxy. It gives every request the same answer
    and keeps the requests it was sent."""

    def __init__(
        self,
        status: int = 200,
        body: Any = None,
        error: Exception | None = None,
    ) -> None:
        self.status = status
        self.body = BODY if body is None else body
        self.error = error
        self.sent: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append(request)
        if self.error is not None:
            raise self.error
        return httpx2.Response(self.status, json=self.body, headers=HEADERS)


def client(store: InMemoryObjectStore, proxy: Proxy) -> LiteLLMClient:
    return LiteLLMClient(
        httpx2.Client(
            base_url="http://proxy.example:4000",
            transport=httpx2.MockTransport(proxy),
        ),
        store,
    )


def with_usage(**changed: Any) -> dict[str, Any]:
    """The usual response body with some of its usage figures changed."""
    return BODY | {"usage": USAGE | changed}


def stored(store: InMemoryObjectStore, hop: str) -> dict[str, Any]:
    """The content of one of the stored files, by the part of the
    exchange it holds."""
    (key,) = [k for k in store.objects if k.endswith(f"/{hop}.json.gz")]
    return dict(json.loads(gzip.decompress(store.objects[key])))


def test_the_request_goes_to_the_chat_completions_endpoint() -> None:
    proxy = Proxy()

    client(NoStore(), proxy).complete(REQUEST, purpose="judge")

    (sent,) = proxy.sent
    assert sent.url.path == "/v1/chat/completions"
    assert json.loads(sent.content) == REQUEST


def test_each_kind_of_token_is_counted_separately() -> None:
    result = client(NoStore(), Proxy()).complete(REQUEST, purpose="judge")

    assert result.record.input_tokens == 8106
    assert result.record.cached_input_tokens == 3934
    assert result.record.output_tokens == 98
    assert result.record.reasoning_output_tokens == 60
    assert result.record.total_tokens == 8204
    assert result.record.finish_reasons == ("stop",)


def test_tokens_written_to_a_cache_are_read_from_the_top_of_usage() -> None:
    body = with_usage(cache_creation_input_tokens=5840)

    result = client(NoStore(), Proxy(body=body)).complete(
        REQUEST, purpose="judge"
    )

    assert result.record.cache_creation_input_tokens == 5840


def test_tokens_written_to_a_cache_are_read_from_the_details() -> None:
    body = with_usage(
        prompt_tokens_details={
            "cached_tokens": 0,
            "cache_creation_tokens": 5840,
        }
    )

    result = client(NoStore(), Proxy(body=body)).complete(
        REQUEST, purpose="judge"
    )

    assert result.record.cache_creation_input_tokens == 5840


def test_a_reported_zero_is_recorded_as_zero() -> None:
    """The details say zero tokens were written to a cache. That is the
    answer, even though the top of the usage block gives another
    figure."""
    body = with_usage(
        prompt_tokens_details={
            "cached_tokens": 5840,
            "cache_creation_tokens": 0,
        },
        cache_creation_input_tokens=77,
    )

    result = client(NoStore(), Proxy(body=body)).complete(
        REQUEST, purpose="judge"
    )

    assert result.record.cache_creation_input_tokens == 0


def test_a_count_the_response_does_not_give_is_none() -> None:
    result = client(NoStore(), Proxy()).complete(REQUEST, purpose="judge")

    assert result.record.cache_creation_input_tokens is None


def test_the_cost_is_kept_as_the_proxy_wrote_it_and_as_nanodollars() -> None:
    result = client(NoStore(), Proxy()).complete(REQUEST, purpose="judge")

    assert result.record.cost_usd == "6e-07"
    assert result.record.cost_nanodollars == 600
    assert result.record.cost_input_usd == "6e-07"


def test_three_durations_are_recorded() -> None:
    """How long the provider took, how long the proxy added, and how
    long this client waited."""
    result = client(NoStore(), Proxy()).complete(REQUEST, purpose="judge")

    assert result.record.provider_duration_ms == 868.981
    assert result.record.proxy_overhead_ms == 4.891
    assert result.record.client_duration_ms > 0


def test_the_record_says_who_was_asked_who_answered_and_why() -> None:
    result = client(NoStore(), Proxy()).complete(
        REQUEST, purpose="judge", policy_id="P-01", attempt=2
    )

    assert result.record.call_id == CALL_ID
    assert result.record.purpose == "judge"
    assert result.record.policy_id == "P-01"
    assert result.record.attempt == 2
    assert result.record.requested_model == "small"
    assert result.record.answered_model == "quick-1"
    assert result.record.model_id == "0123456789abcdef"
    assert result.record.api_base == "https://models.example"
    assert (result.record.retries, result.record.fallbacks) == (0, 0)
    assert result.status_code == 200
    assert result.payload == BODY


def test_a_call_the_provider_refused_is_recorded() -> None:
    proxy = Proxy(status=429, body={"error": {"message": "slow down"}})

    result = client(NoStore(), proxy).complete(REQUEST, purpose="judge")

    assert result.record.status == "refused"
    assert result.record.http_status == 429
    assert result.record.call_id == CALL_ID
    assert result.error is None


def test_a_call_that_got_no_answer_is_recorded() -> None:
    proxy = Proxy(error=httpx2.ConnectError("no route"))

    result = client(NoStore(), proxy).complete(REQUEST, purpose="judge")

    assert result.record.status == "unreachable"
    assert result.record.http_status is None
    assert result.record.error == "no route"
    assert result.record.call_id.startswith("local-")
    assert result.status_code is None
    assert isinstance(result.error, httpx2.ConnectError)


def test_three_files_are_stored_in_one_dated_folder() -> None:
    store = InMemoryObjectStore()

    result = client(store, Proxy()).complete(REQUEST, purpose="judge")

    assert sorted(k.rsplit("/", 1)[-1] for k in store.objects) == [
        "agent_request.json.gz",
        "fact.json.gz",
        "proxy_response.json.gz",
    ]
    (folder,) = {k.rsplit("/", 1)[0] for k in store.objects}
    assert folder == result.record.archive_folder
    prefix, year, month, day, archive_id = folder.split("/")
    assert prefix == "exchanges"
    assert (len(year), len(month), len(day)) == (4, 2, 2)
    assert len(archive_id) == 32


def test_the_proxy_is_told_the_folder_in_a_request_header() -> None:
    store = InMemoryObjectStore()
    proxy = Proxy()

    client(store, proxy).complete(REQUEST, purpose="judge")

    (sent,) = proxy.sent
    assert {k.rsplit("/", 1)[0] for k in store.objects} == {
        sent.headers[ARCHIVE_HEADER]
    }


def test_the_request_and_the_response_are_stored_whole() -> None:
    store = InMemoryObjectStore()

    client(store, Proxy()).complete(REQUEST, purpose="judge")

    assert stored(store, "agent_request")["body"] == REQUEST
    response = stored(store, "proxy_response")
    assert response["status"] == 200
    assert response["body"] == BODY
    assert response["headers"]["x-litellm-response-cost"] == "6e-07"


def test_the_fact_file_lists_the_other_files_with_their_hashes() -> None:
    store = InMemoryObjectStore()

    result = client(store, Proxy()).complete(REQUEST, purpose="judge")

    fact = stored(store, "fact")
    listed = {o["hop"]: o for o in fact["objects"]}
    assert sorted(listed) == ["agent_request", "proxy_response"]
    for entry in listed.values():
        assert len(entry["sha256"]) == 64
        assert entry["bytes"] == len(store.objects[entry["key"]])
    assert fact["schema_version"] == 1
    assert fact["content_present"] is True
    assert sorted(o.hop for o in result.record.objects) == [
        "agent_request",
        "fact",
        "proxy_response",
    ]


def test_the_fact_file_names_the_two_files_the_proxy_writes() -> None:
    store = InMemoryObjectStore()

    client(store, Proxy()).complete(REQUEST, purpose="judge")

    fact = stored(store, "fact")
    theirs = {o["hop"]: o["key"] for o in fact["written_by_the_proxy"]}
    assert sorted(theirs) == ["llm_response", "proxy_request"]
    assert all(
        key.startswith(fact["archive_folder"]) for key in theirs.values()
    )


def test_the_fact_file_has_the_records_figures() -> None:
    store = InMemoryObjectStore()

    client(store, Proxy()).complete(REQUEST, purpose="judge", policy_id="P-01")

    fact = stored(store, "fact")
    assert fact["cost_nanodollars"] == 600
    assert fact["cached_input_tokens"] == 3934
    assert fact["policy_id"] == "P-01"
    assert fact["started_at"] and fact["ended_at"]


def test_a_refused_calls_files_are_stored_too() -> None:
    store = InMemoryObjectStore()
    proxy = Proxy(status=500, body={"error": {"message": "upstream"}})

    client(store, proxy).complete(REQUEST, purpose="judge")

    assert stored(store, "fact")["status"] == "refused"
    assert stored(store, "proxy_response")["status"] == 500


def test_with_no_store_set_up_the_record_is_still_complete() -> None:
    store = NoStore()

    result = client(store, Proxy()).complete(REQUEST, purpose="judge")

    assert result.record.cost_nanodollars == 600
    assert result.record.objects == ()
    assert store.objects == {}


def test_a_store_that_refuses_does_not_fail_the_call() -> None:
    result = client(RefusingStore(), Proxy()).complete(
        REQUEST, purpose="judge"
    )

    assert result.record.status == "ok"
    assert result.record.objects == ()
