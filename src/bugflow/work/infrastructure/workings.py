"""Store a run's workings in the object store.

A run's workings are the full record of what happened in it: every
message and event. A run carries a reference to them and not the
workings themselves, because a workflow engine records everything
passed between steps and the workings are large.

The reference is the SHA-256 hash of the stored bytes. So the stored
object can be checked against the reference, and storing the same
workings twice stores one object.
"""

import gzip
import hashlib
import json
from collections.abc import Sequence
from typing import Any

from bugflow.shared.domain.services.object_store import ObjectStoreService

#: The first part of the key every run's workings are stored under.
WORKINGS = "workings"


def archive_workings(
    objects: ObjectStoreService | None,
    events: Sequence[dict[str, Any]],
) -> str:
    """Store the events as gzipped JSON under
    ``workings/<reference>.json.gz`` and return the reference.

    Returns an empty string if nothing was stored: there were no
    events, there is no object store, or the store refused. A caller
    that gets an empty string keeps the events in the run. Failing to
    store the workings never fails the run.
    """
    if not events or objects is None or not objects.configured:
        return ""
    body = gzip.compress(
        json.dumps(list(events), default=str, sort_keys=True).encode()
    )
    reference = hashlib.sha256(body).hexdigest()
    key = f"{WORKINGS}/{reference}.json.gz"
    try:
        # A key is written once. The same workings give the same key,
        # so if the key is there the object is already stored.
        if not objects.has(key):
            objects.put(key, body)
    except Exception:
        return ""
    return reference
