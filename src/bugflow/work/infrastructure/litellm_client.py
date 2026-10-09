"""Call a model through a LiteLLM proxy, and keep a record of the call.

Every call to a model goes through ``LiteLLMClient.complete``. It makes
a ``CallRecord`` for each call, whether the call succeeded, was refused
or got no answer. It also stores the call's content in the object
store, if one is set up.

The exchange with a model has four parts, and each is stored as one
file:

- ``agent_request``: what this client sent to the proxy.
- ``proxy_request``: what the proxy sent to the provider.
- ``llm_response``: what the provider answered.
- ``proxy_response``: what the proxy answered to this client, with its
  headers. The headers give the cost the proxy worked out, how long
  the provider took, and how many retries were needed.

This client writes the first and the last. The proxy writes the middle
two, if it has a callback set up to do so. A fifth file, ``fact``, is
the ``CallRecord`` as JSON, so that the object store can be read
without the database.

All five files of one call go in one folder. This client chooses the
folder before it sends the request, and tells the proxy in a header. A
call that times out has no response to take an id from, so the folder
cannot be chosen afterwards.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any

import httpx2
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from bugflow.shared.domain.models.call_record import (
    CallRecord,
    CallStatus,
    Purpose,
    StoredObject,
    nanodollars,
)
from bugflow.shared.domain.services.object_store import ObjectStoreService
from bugflow.shared.infrastructure.serde import to_json

_TRACER = trace.get_tracer("bugflow.work")

#: The names of the three files this client writes.
AGENT_REQUEST = "agent_request"
PROXY_RESPONSE = "proxy_response"
FACT = "fact"

#: The names of the two files the proxy writes. The fact file lists
#: them without a hash, because this client never sees them. A reader
#: who finds them missing knows the proxy did not write them.
PROXY_REQUEST = "proxy_request"
LLM_RESPONSE = "llm_response"

#: The request header that tells the proxy which folder to write its
#: two files in.
ARCHIVE_HEADER = "x-bugflow-archive-folder"

#: The version of the fact file's layout. Raise it when the layout
#: changes. It is written into each fact file, so that a file can be
#: read correctly long after this code has changed.
FACT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CallResult:
    """What a call returned, and the record made of it.

    The caller decides what the status means. For example only the
    caller knows whether a 429 that mentions a daily quota should be
    treated differently from one that mentions a rate limit.
    """

    record: CallRecord
    #: The HTTP status, or None if no answer came.
    status_code: int | None
    #: The response headers, with their names in lower case.
    headers: dict[str, str]
    #: The response body as JSON, or None if it was not JSON.
    payload: dict[str, Any] | None
    #: The response body as text, or None if no answer came.
    text: str | None
    #: The error, if the request could not be sent or timed out.
    error: Exception | None = None


def _digest(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _float(headers: dict[str, str], name: str) -> float | None:
    raw = headers.get(name)
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _int(headers: dict[str, str], name: str) -> int | None:
    value = _float(headers, name)
    return int(value) if value is not None else None


def _usage(payload: dict[str, Any] | None, *names: str) -> int | None:
    """Read one token count from the response's ``usage`` block.

    ``names`` is the path to it. Some counts are nested: cached input
    tokens are under ``prompt_tokens_details``, and reasoning tokens
    under ``completion_tokens_details``. Returns None if the response
    does not give the count.
    """
    usage: Any = (payload or {}).get("usage") or {}
    for name in names:
        if not isinstance(usage, dict):
            return None
        usage = usage.get(name)
        if usage is None:
            return None
    return int(usage) if isinstance(usage, int) else None


def _first(*values: int | None) -> int | None:
    """The first of the values that is not None.

    Zero counts as a value. A response that reports zero in one place
    has answered, and the next place must not be looked at.
    """
    for value in values:
        if value is not None:
            return value
    return None


class LiteLLMClient:
    def __init__(
        self,
        client: httpx2.Client,
        objects: ObjectStoreService,
        prefix: str = "exchanges",
    ) -> None:
        """``client`` is an HTTP client whose base URL is the proxy,
        with whatever key the proxy needs. ``prefix`` is the first part
        of every key this client stores under."""
        self._client = client
        self._objects = objects
        self._prefix = prefix

    def complete(
        self,
        request: dict[str, Any],
        purpose: Purpose,
        policy_id: str | None = None,
        attempt: int = 1,
    ) -> CallResult:
        """Send a chat completion request and return what came back.

        ``request`` is the body to send. ``purpose`` and ``policy_id``
        say why the call was made, and ``attempt`` which try this is.
        They are copied into the record.

        An error status, or no answer at all, is returned and not
        raised.
        """
        model = str(request.get("model") or "")
        attributes: dict[str, str] = {
            "gen_ai.operation.name": "chat",
            "gen_ai.request.model": model,
            "server.address": str(self._client.base_url),
            "bugflow.purpose": purpose,
        }
        if policy_id is not None:
            attributes["bugflow.policy_id"] = policy_id
        with _TRACER.start_as_current_span(
            f"chat {model}" if model else "chat",
            kind=SpanKind.CLIENT,
            attributes=attributes,
        ) as span:
            started = datetime.now(UTC)
            folder = self.folder_for(started, uuid.uuid4().hex)
            error: Exception | None = None
            response: httpx2.Response | None = None
            try:
                response = self._client.post(
                    "/v1/chat/completions",
                    json=request,
                    headers={ARCHIVE_HEADER: folder},
                )
            except httpx2.RequestError as exc:  # includes timeouts
                error = exc
            ended = datetime.now(UTC)
            if error is not None:
                span.record_exception(error)

            result = self._record(
                request=request,
                folder=folder,
                response=response,
                error=error,
                purpose=purpose,
                policy_id=policy_id,
                attempt=attempt,
                started=started,
                ended=ended,
                span=span,
            )
            self._describe(span, result.record)
            return result

    def _record(
        self,
        *,
        request: dict[str, Any],
        folder: str,
        response: httpx2.Response | None,
        error: Exception | None,
        purpose: Purpose,
        policy_id: str | None,
        attempt: int,
        started: datetime,
        ended: datetime,
        span: trace.Span,
    ) -> CallResult:
        """Build the record of a call from its response, store the
        call's files, and return the result."""
        headers = (
            {k.lower(): v for k, v in response.headers.items()}
            if response is not None
            else {}
        )
        payload: dict[str, Any] | None = None
        text: str | None = None
        if response is not None:
            text = response.text
            try:
                payload = response.json()
            except ValueError:
                payload = None

        status: CallStatus
        if response is None:
            status = "unreachable"
        elif response.status_code >= 400:
            status = "refused"
        else:
            status = "ok"

        # Use the proxy's id for the call if it gave one. A call the
        # proxy never answered gets an id made here, with a prefix the
        # proxy does not use.
        call_id = headers.get("x-litellm-call-id") or f"local-{uuid.uuid4()}"
        context = span.get_span_context()

        record = CallRecord(
            call_id=call_id,
            archive_folder=folder,
            purpose=purpose,
            policy_id=policy_id,
            status=status,
            http_status=response.status_code if response is not None else None,
            error=str(error) if error is not None else None,
            requested_model=str(request.get("model") or ""),
            answered_model=str((payload or {}).get("model") or "") or None,
            model_id=headers.get("x-litellm-model-id"),
            model_group=headers.get("x-litellm-model-group"),
            api_base=headers.get("x-litellm-model-api-base"),
            proxy_version=headers.get("x-litellm-version"),
            attempt=attempt,
            retries=_int(headers, "x-litellm-attempted-retries"),
            fallbacks=_int(headers, "x-litellm-attempted-fallbacks"),
            finish_reasons=tuple(
                str(choice.get("finish_reason"))
                for choice in (payload or {}).get("choices") or []
                if choice.get("finish_reason")
            ),
            input_tokens=_usage(payload, "prompt_tokens"),
            output_tokens=_usage(payload, "completion_tokens"),
            cached_input_tokens=_usage(
                payload, "prompt_tokens_details", "cached_tokens"
            ),
            # The count of tokens written to a cache is in one of two
            # places, depending on the provider. The proxy moves it
            # under prompt_tokens_details for some and leaves it at the
            # top of the usage block for others.
            cache_creation_input_tokens=_first(
                _usage(
                    payload, "prompt_tokens_details", "cache_creation_tokens"
                ),
                _usage(payload, "cache_creation_input_tokens"),
            ),
            reasoning_output_tokens=_usage(
                payload, "completion_tokens_details", "reasoning_tokens"
            ),
            total_tokens=_usage(payload, "total_tokens"),
            cost_usd=headers.get("x-litellm-response-cost"),
            cost_nanodollars=nanodollars(
                headers.get("x-litellm-response-cost")
            ),
            cost_input_usd=headers.get("x-litellm-response-cost-input"),
            cost_output_usd=headers.get("x-litellm-response-cost-output"),
            cost_cache_read_usd=headers.get(
                "x-litellm-response-cost-cache-read"
            ),
            cost_cache_creation_usd=headers.get(
                "x-litellm-response-cost-cache-creation"
            ),
            cost_reasoning_usd=headers.get(
                "x-litellm-response-cost-reasoning"
            ),
            started_at=started,
            ended_at=ended,
            client_duration_ms=(ended - started).total_seconds() * 1000,
            provider_duration_ms=_float(
                headers, "x-litellm-response-duration-ms"
            ),
            proxy_overhead_ms=_float(
                headers, "x-litellm-overhead-duration-ms"
            ),
            trace_id=format(context.trace_id, "032x")
            if context.is_valid
            else None,
            span_id=format(context.span_id, "016x")
            if context.is_valid
            else None,
        )
        record = replace(
            record, objects=self._keep(record, request, text, headers, payload)
        )
        return CallResult(
            record=record,
            status_code=response.status_code if response is not None else None,
            headers=headers,
            payload=payload,
            text=text,
            error=error,
        )

    def _keep(
        self,
        record: CallRecord,
        request: dict[str, Any],
        text: str | None,
        headers: dict[str, str],
        payload: dict[str, Any] | None,
    ) -> tuple[StoredObject, ...]:
        """Store the request and the response, then the fact file, and
        return what was stored.

        The fact file is written last so that it can give the hashes of
        the other two. If the process stops part way, files are left
        that no fact file lists. That is harmless.

        Returns nothing if no object store is set up.
        """
        if not self._objects.configured:
            return ()

        kept: list[StoredObject] = []
        kept.extend(self._put(record, AGENT_REQUEST, {"body": request}) or [])
        kept.extend(
            self._put(
                record,
                PROXY_RESPONSE,
                {
                    "status": record.http_status,
                    "headers": headers,
                    "body": payload,
                    "text": None if payload is not None else text,
                },
            )
            or []
        )
        fact = to_json(replace(record, objects=tuple(kept)))
        fact["schema_version"] = FACT_SCHEMA_VERSION
        fact["content_present"] = bool(kept)
        fact["written_by_the_proxy"] = [
            {"hop": hop, "key": f"{record.archive_folder}/{hop}.json.gz"}
            for hop in (PROXY_REQUEST, LLM_RESPONSE)
        ]
        kept.extend(self._put(record, FACT, fact) or [])
        return tuple(kept)

    def _put(
        self, record: CallRecord, hop: str, document: Any
    ) -> list[StoredObject]:
        """Store one file as gzipped JSON. Returns an empty list if the
        store refuses: a file that could not be stored does not fail
        the call."""
        body = gzip.compress(
            json.dumps(document, default=str, sort_keys=True).encode()
        )
        key = self.key_for(record, hop)
        try:
            self._objects.put(key, body)
        except Exception:
            return []
        return [
            StoredObject(
                hop=hop, key=key, sha256=_digest(body), bytes=len(body)
            )
        ]

    def folder_for(self, started: datetime, archive_id: str) -> str:
        """The folder for one call's files:
        ``<prefix>/YYYY/MM/DD/<archive id>``.

        The date is in the key so that a rule on the bucket, such as
        one that deletes old files, can select by month.
        """
        day = started.astimezone(UTC).strftime("%Y/%m/%d")
        return f"{self._prefix}/{day}/{archive_id}"

    def key_for(self, record: CallRecord, hop: str) -> str:
        """The key of one of a call's files."""
        return f"{record.archive_folder}/{hop}.json.gz"

    def _describe(self, span: trace.Span, record: CallRecord) -> None:
        """Copy the model, the token counts and the status from the
        record to the trace span."""
        if record.answered_model:
            span.set_attribute("gen_ai.response.model", record.answered_model)
        for value, name in (
            (record.input_tokens, "gen_ai.usage.input_tokens"),
            (record.output_tokens, "gen_ai.usage.output_tokens"),
        ):
            if value is not None:
                span.set_attribute(name, value)
        if record.finish_reasons:
            span.set_attribute(
                "gen_ai.response.finish_reasons", list(record.finish_reasons)
            )
        # The cost is left off. The proxy puts it on its own span.
        span.set_attribute("bugflow.call_id", record.call_id)
        if record.status != "ok":
            # Mark the span as an error, so that a call the provider
            # refused does not look like a healthy one in a trace.
            span.set_attribute(
                "error.type", record.error or str(record.http_status)
            )
            span.set_status(
                Status(StatusCode.ERROR, record.error or record.status)
            )
