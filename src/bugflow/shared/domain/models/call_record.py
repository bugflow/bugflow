"""The record of one call to a language model: what was asked for, what
answered, how many tokens it used, what it cost and how long it took.

The figures are kept separately and not added together, because
different questions need different ones. Tokens read from a cache are
not counted with ordinary input tokens. Reasoning tokens are not counted
with ordinary output tokens. The time the provider took is not the time
the caller waited.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal

#: Why a call was made.
Purpose = Literal["judge", "grade", "calibrate", "reproduce"]

#: How a call ended. "refused" means the provider said no, for example
#: because of a quota, a rate limit or a rejected key. "unreachable"
#: means no answer came at all.
CallStatus = Literal["ok", "refused", "unreachable"]

#: The number of nanodollars in a dollar. Costs are added up in
#: nanodollars, as whole numbers, because one call can cost less than a
#: millionth of a dollar and sums of fractions drift.
NANODOLLARS = Decimal(10) ** 9


def nanodollars(value: str | None) -> int | None:
    """Convert a cost in dollars, given as text such as "0.0000006", to a
    whole number of nanodollars. Returns None if ``value`` is None or is
    not a number."""
    if value is None:
        return None
    try:
        return int((Decimal(value) * NANODOLLARS).to_integral_value())
    except (ArithmeticError, ValueError):
        return None


@dataclass(frozen=True, kw_only=True)
class StoredObject:
    """One stored file belonging to a call, such as the request or the
    response.

    ``hop`` says which part of the exchange the file is. ``key`` is
    where it is in the object store. ``sha256`` is the hash of its
    content, so that the file found there later can be checked against
    what was written.
    """

    hop: str
    key: str
    sha256: str
    bytes: int
    encoding: str = "gzip"


@dataclass(frozen=True, kw_only=True)
class CallRecord:
    """One call to a model, however it ended."""

    #: The id of the call. The model proxy uses the same id, so it joins
    #: this record to the proxy's own.
    call_id: str
    #: Where this call's files are kept in the object store.
    archive_folder: str = ""
    purpose: Purpose
    #: The policy the call was made for, if it was made for one.
    policy_id: str | None = None
    status: CallStatus = "ok"
    http_status: int | None = None
    error: str | None = None

    #: The model that was asked for. This is a role name such as
    #: "large", not a vendor's model name.
    requested_model: str
    #: The model that actually answered. It can differ from the one
    #: asked for when the proxy falls back to another.
    answered_model: str | None = None
    model_id: str | None = None
    model_group: str | None = None
    api_base: str | None = None
    proxy_version: str | None = None

    attempt: int = 1
    retries: int | None = None
    fallbacks: int | None = None
    finish_reasons: tuple[str, ...] = ()

    input_tokens: int | None = None
    output_tokens: int | None = None
    #: Input tokens that were read from the provider's cache. They are
    #: billed at a lower rate.
    cached_input_tokens: int | None = None
    #: Input tokens that were written to the provider's cache. They are
    #: billed at a higher rate. Kept apart from the reads, so that how
    #: often caching pays off can be worked out.
    cache_creation_input_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    total_tokens: int | None = None

    #: The costs as text, exactly as the proxy reported them, and the
    #: total again as a whole number of nanodollars for adding up.
    cost_usd: str | None = None
    cost_nanodollars: int | None = None
    cost_input_usd: str | None = None
    cost_output_usd: str | None = None
    cost_cache_read_usd: str | None = None
    cost_cache_creation_usd: str | None = None
    cost_reasoning_usd: str | None = None

    started_at: datetime
    ended_at: datetime
    #: Three durations in milliseconds: how long the caller waited, how
    #: long the provider took, and how long the proxy added. The gaps
    #: between them show queueing and retries.
    client_duration_ms: float
    provider_duration_ms: float | None = None
    proxy_overhead_ms: float | None = None

    trace_id: str | None = None
    span_id: str | None = None

    objects: tuple[StoredObject, ...] = ()
