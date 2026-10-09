"""An object store backed by an S3 bucket.

It works with any service that speaks the S3 API, hosted or self-hosted:
only the endpoint differs. An object is written once and never overwritten.
"""

from __future__ import annotations

from typing import Any, cast

from bugflow.shared.domain.errors import ObjectStoreError

#: The error codes an S3 service gives for a missing object. A read
#: gives the first; a check for existence gives one of the others.
ABSENT = ("NoSuchKey", "404", "NotFound")


def _absent(exc: Exception) -> bool:
    """Whether an error from the S3 client means "no such object", as opposed
    to a failure.
    """
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    return str(response.get("Error", {}).get("Code", "")) in ABSENT


class S3ObjectStore:
    def __init__(
        self,
        endpoint: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
        client: Any = None,
    ) -> None:
        self._bucket = bucket
        if client is not None:
            self._client = client
            return
        import boto3

        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    def put(
        self,
        key: str,
        body: bytes,
        content_type: str = "application/json",
        content_encoding: str | None = "gzip",
    ) -> None:
        extra = {"ContentType": content_type}
        if content_encoding:
            extra["ContentEncoding"] = content_encoding
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=body, **extra
            )
        except Exception as exc:
            raise ObjectStoreError(f"could not write {key}: {exc}") from exc

    def get(self, key: str) -> bytes | None:
        try:
            found = self._client.get_object(Bucket=self._bucket, Key=key)
            return cast(bytes, found["Body"].read())
        except Exception as exc:
            if _absent(exc):
                return None
            raise ObjectStoreError(f"could not read {key}: {exc}") from exc

    def has(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
        except Exception as exc:
            if _absent(exc):
                return False
            raise ObjectStoreError(
                f"could not ask after {key}: {exc}"
            ) from exc
        return True

    @property
    def configured(self) -> bool:
        return True
