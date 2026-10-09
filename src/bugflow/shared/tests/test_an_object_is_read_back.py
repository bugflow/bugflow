"""What was put in an object store is read back as it was written.

The S3 adapter is run over a real boto3 client whose answers botocore's
own stubber supplies, so the calls it makes and the errors it reads are
the service's shapes and not a double's.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from botocore.response import StreamingBody
from botocore.stub import Stubber

from bugflow.shared.domain.errors import ObjectStoreError
from bugflow.shared.infrastructure.in_memory_object_store import (
    InMemoryObjectStore,
)
from bugflow.shared.infrastructure.s3_object_store import S3ObjectStore

BUCKET = "kept"
KEY = "archive/blocks/bafkreiexample"
BODY = b"\x00sealed bytes\xff"


@pytest.fixture
def s3() -> Iterator[tuple[S3ObjectStore, Stubber]]:
    client: Any = boto3.client(
        "s3",
        endpoint_url="https://objects.invalid",
        aws_access_key_id="key",
        aws_secret_access_key="secret",
        region_name="us-east-1",
    )
    with Stubber(client) as stubber:
        yield S3ObjectStore("", BUCKET, "", "", client=client), stubber
        stubber.assert_no_pending_responses()


def test_an_object_in_memory_is_read_back_as_written() -> None:
    store = InMemoryObjectStore()
    assert (store.get(KEY), store.has(KEY)) == (None, False)
    store.put(KEY, BODY, "application/octet-stream", None)
    assert (store.get(KEY), store.has(KEY)) == (BODY, True)


def test_an_object_in_a_bucket_is_read_back_as_written(
    s3: tuple[S3ObjectStore, Stubber],
) -> None:
    store, stubber = s3
    stubber.add_response(
        "get_object",
        {"Body": StreamingBody(io.BytesIO(BODY), len(BODY))},
        {"Bucket": BUCKET, "Key": KEY},
    )
    stubber.add_response("head_object", {}, {"Bucket": BUCKET, "Key": KEY})
    assert store.get(KEY) == BODY
    assert store.has(KEY) is True


def test_an_object_that_is_not_in_the_bucket_is_absent_not_an_error(
    s3: tuple[S3ObjectStore, Stubber],
) -> None:
    store, stubber = s3
    stubber.add_client_error(
        "get_object", service_error_code="NoSuchKey", http_status_code=404
    )
    stubber.add_client_error(
        "head_object", service_error_code="404", http_status_code=404
    )
    assert store.get(KEY) is None
    assert store.has(KEY) is False


@pytest.mark.parametrize("operation", ["get_object", "head_object"])
def test_a_bucket_that_cannot_be_read_says_so(
    s3: tuple[S3ObjectStore, Stubber], operation: str
) -> None:
    """Refused access is not absence: a reader whose store is down must
    not be told the bytes were never there."""
    store, stubber = s3
    stubber.add_client_error(
        operation, service_error_code="AccessDenied", http_status_code=403
    )
    read = store.get if operation == "get_object" else store.has
    with pytest.raises(ObjectStoreError):
        read(KEY)
