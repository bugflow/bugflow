"""Reads a Forgejo webhook delivery into a ``Delivery``.

Forgejo's deliveries look like GitHub's and even carry GitHub's headers,
but they differ in two ways that matter, seen in deliveries recorded from
Forgejo 16.0.4:

- A push to a pull request's branch has the action "synchronized". GitHub
  says "synchronize".
- A comment on an ordinary issue still has a ``pull_request`` key, set to
  null. On GitHub the key is only present for a pull request.
"""

from collections.abc import Mapping
from typing import Any

from bugflow.forge.domain.models.delivery import (
    Delivery,
    DeliveryComment,
    forge_time,
)
from bugflow.shared.domain.values.pull_request_ref import PullRequestRef

# Forgejo's names for pull request actions, where they differ from GitHub's.
# The rest of the code uses GitHub's names.
_ACTIONS = {"synchronized": "synchronize"}


def delivery_from_forgejo(
    headers: Mapping[str, str], body: dict[str, Any]
) -> Delivery:
    """Build a ``Delivery`` from the headers and JSON body of a request
    Forgejo sent. Raises ``ValueError`` if the headers that identify a
    Forgejo delivery are missing.
    """
    lowered = {name.lower(): value for name, value in headers.items()}
    try:
        event = lowered["x-forgejo-event"]
        delivery_id = lowered["x-forgejo-delivery"]
    except KeyError as exc:
        raise ValueError(
            f"not a Forgejo delivery: missing the {exc.args[0]} header"
        ) from exc

    repository = body.get("repository") or {}
    owner = (repository.get("owner") or {}).get("login")
    name = repository.get("name")
    full_name = f"{owner}/{name}" if owner and name else None
    action = body.get("action")

    ref = None
    if event == "pull_request" and owner and name and "number" in body:
        ref = PullRequestRef(
            forge="forgejo", owner=owner, repo=name, number=body["number"]
        )
        if isinstance(action, str):
            action = _ACTIONS.get(action, action)

    comment = None
    if event == "issue_comment":
        issue = body.get("issue") or {}
        # A comment on an ordinary issue has a ``pull_request`` key too, set to
        # null, so the key's value is checked and not just its presence.
        if owner and name and "number" in issue and issue.get("pull_request"):
            ref = PullRequestRef(
                forge="forgejo", owner=owner, repo=name, number=issue["number"]
            )
        raw = body.get("comment") or {}
        if "id" in raw:
            comment = DeliveryComment(
                comment_id=raw["id"],
                author=(raw.get("user") or {}).get("login") or "",
                body=raw.get("body") or "",
            )

    pull = body.get("pull_request") or {}
    return Delivery(
        forge="forgejo",
        delivery_id=delivery_id,
        event=event,
        action=action,
        repository=full_name,
        ref=ref,
        comment=comment,
        merged=bool(pull.get("merged")),
        merge_commit_sha=pull.get("merge_commit_sha") or None,
        updated_at=forge_time(pull.get("updated_at")),
    )
