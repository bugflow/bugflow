"""Two ways to hash content, so that a later check can tell whether the
content has changed.

A judgement about some content is only worth keeping while the content
is the same. So the code that judges records a hash of what it read,
and later compares that with a hash of what is there now.

There are two functions because content comes in two forms: rows of
strings, and a JSON value. Hashes made by both are already stored.
Changing how either is computed would make every stored hash differ
from its content, and everything would look changed at once.
"""

import hashlib
import json
from collections.abc import Iterable
from typing import Any


def digest_rows(rows: Iterable[tuple[str, ...]]) -> str:
    """The first 16 hexadecimal characters of a SHA-256 hash of rows of
    strings.

    The rows are sorted first, so the order they are given in does not
    change the result. Each field is followed by a zero byte, so moving
    a character from one field to the next does change it.
    """
    h = hashlib.sha256()
    for row in sorted(rows):
        for field in row:
            h.update(field.encode("utf-8"))
            h.update(b"\x00")
    return h.hexdigest()[:16]


def content_hash(value: Any) -> str:
    """The SHA-256 hash of a JSON value, as 64 hexadecimal characters.

    The value is written as JSON with its keys sorted and no spaces, so
    the order of an object's keys does not change the result.
    """
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
