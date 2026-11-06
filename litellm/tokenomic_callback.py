"""The proxy's half of an exchange, kept beside the worker's.

The worker's ``LiteLLMClient`` keeps what it sent the proxy and what
the proxy answered, and names in its fact file two more files only
the proxy can write: ``proxy_request``, what the proxy sent the
provider, in the provider's own shape, and ``llm_response``, what the
provider answered before LiteLLM normalised it. Neither is a copy of
the other two. A question about prompt caching is answered by the
provider-native request, and a question about what the worker asked is
not.

This file is mounted into the proxy's container and named in its
configuration. It writes to the same bucket the worker writes to, into
the folder the worker named in a header, so the five files of one
exchange are one directory.

It never breaks a call. A judgement whose evidence could not be stored
is still a judgement, and every figure about it is journalled by the
worker either way.
"""

from __future__ import annotations

import gzip
import json
import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

# This file runs inside LiteLLM's container and is tested outside it.
# The base class contributes no behaviour used here, because LiteLLM
# calls these methods by name, so standing in for it when the package
# is absent costs nothing and buys a file that is tested rather than
# only deployed.
if TYPE_CHECKING:
    # Typed as the stand-in either way: inside the image the real base
    # is untyped, and strict mode will not subclass Any.
    class CustomLogger:
        pass

else:  # pragma: no cover - the import that matters only in the image
    try:
        from litellm.integrations.custom_logger import CustomLogger
    except ImportError:

        class CustomLogger:
            pass


#: Set by the worker, per request. Absent, this writes nothing: a call
#: from something that is not keeping an archive is not this file's
#: business.
ARCHIVE_HEADER = "x-bugflow-archive-folder"

PROXY_REQUEST = "proxy_request"
LLM_RESPONSE = "llm_response"


def _client() -> Any:
    endpoint = os.environ.get("TOKENOMIC_S3_ENDPOINT")
    bucket = os.environ.get("TOKENOMIC_S3_BUCKET")
    access = os.environ.get("TOKENOMIC_S3_ACCESS_KEY")
    secret = os.environ.get("TOKENOMIC_S3_SECRET_KEY")
    if not (endpoint and bucket and access and secret):
        return None, None
    import boto3

    return (
        boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access,
            aws_secret_access_key=secret,
            region_name=os.environ.get("TOKENOMIC_S3_REGION") or "us-east-1",
        ),
        bucket,
    )


def folder_from(kwargs: dict[str, Any]) -> str | None:
    """Where the worker said its exchange lives."""
    params = kwargs.get("litellm_params") or {}
    metadata = params.get("metadata") or {}
    headers = metadata.get("headers") or {}
    if not isinstance(headers, dict):
        return None
    for name, value in headers.items():
        if str(name).lower() == ARCHIVE_HEADER and value:
            return str(value)
    return None


def hops(kwargs: dict[str, Any], response: Any) -> dict[str, Any]:
    """The two documents this proxy alone holds.

    ``complete_input_dict`` is the provider-native request, and
    ``original_response`` is what came back before it was normalised.
    Either can be absent, as a call that failed before it was sent has
    no provider request, and an absent hop is written as null rather
    than skipped, so a reader can tell "nothing was sent" from "nobody
    recorded it".
    """
    additional = kwargs.get("additional_args") or {}
    params = kwargs.get("litellm_params") or {}
    raw = kwargs.get("original_response")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        parsed = None
    return {
        PROXY_REQUEST: {
            "body": additional.get("complete_input_dict"),
            # Where it was sent. LiteLLM puts this in different places
            # depending on the path taken, and a provider-native request
            # that does not say which endpoint answered it is half a
            # record.
            "api_base": (
                additional.get("api_base")
                or params.get("api_base")
                or kwargs.get("api_base")
            ),
            "headers": additional.get("headers"),
        },
        LLM_RESPONSE: {
            "body": parsed,
            "text": raw if parsed is None else None,
            "status": "ok" if response is not None else "failed",
        },
    }


class TokenomicArchive(CustomLogger):
    def __init__(self) -> None:
        super().__init__()
        self._s3, self._bucket = _client()

    async def async_log_success_event(
        self, kwargs: Any, response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        self._keep(kwargs, response_obj)

    async def async_log_failure_event(
        self, kwargs: Any, response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        # A refused call is a tokenomic fact, and what the provider said
        # about the refusal is only here.
        self._keep(kwargs, None)

    def log_success_event(
        self, kwargs: Any, response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        self._keep(kwargs, response_obj)

    def log_failure_event(
        self, kwargs: Any, response_obj: Any, start_time: Any, end_time: Any
    ) -> None:
        self._keep(kwargs, None)

    def _keep(self, kwargs: dict[str, Any], response: Any) -> None:
        if self._s3 is None:
            return
        folder = folder_from(kwargs)
        if folder is None:
            return
        documents = hops(kwargs, response)
        for hop, document in documents.items():
            document = dict(document)
            document["call_id"] = kwargs.get("litellm_call_id")
            document["written_at"] = datetime.now(UTC).isoformat(
                timespec="milliseconds"
            )
            try:
                self._s3.put_object(
                    Bucket=self._bucket,
                    Key=f"{folder}/{hop}.json.gz",
                    Body=gzip.compress(
                        json.dumps(
                            document, default=str, sort_keys=True
                        ).encode()
                    ),
                    ContentType="application/json",
                    ContentEncoding="gzip",
                )
            except Exception:
                continue


archive = TokenomicArchive()
